"""接入中心（V1.1）：可视化 API 接入配置台。

边界（写在最前面，因为这是整个模块存在的前提）：
- **不连接真实店铺**：本模块没有任何发起外部 HTTP 请求的代码路径。
  刻意不提供"测试连通性"端点——没有出口就没有 SSRF，这比维护 URL 白名单可靠。
- **不保存凭证**：请求模型里根本没有 api_key / access_token / client_secret 字段，
  表里也没有对应列。凭证进不来、存不下、也就回显不了。
- **不存在 connected**：status 只有 draft。做不到的事不在界面上假装做到了。

真实平台 OAuth 与订单同步属于 V2，需真实店铺授权后实施。
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import IntegrationConfig, User
from app.routers.auth import require_admin
from app.schemas import (
    _CREDENTIAL_FIELDS,
    IntegrationDraftCreate,
    IntegrationDraftOut,
    ProviderBlueprint,
)
from app.services import audit

# 整个路由挂 require_admin：agent 访问任何一个端点都是 403，
# 不依赖前端"不显示入口"——前端藏起来只是体验，后端拒绝才是权限。
router = APIRouter(
    prefix="/api/integrations",
    tags=["integrations"],
    dependencies=[Depends(require_admin)],
)

# 各平台接入清单。**全部是本地静态模板**，生成过程不发起任何网络请求。
# 环境变量名只给"名字"，不给值——值该由部署方自己填进运行环境。
_BLUEPRINTS: dict[str, dict] = {
    "shopify": {
        "display_name": "Shopify",
        "auth_type": "OAuth 2.0（Authorization Code）",
        "required_scopes": ["read_orders", "read_fulfillments", "read_customers"],
        "webhook_callback_path": "/api/integrations/webhook/shopify",
        "env_var_names": ["SHOPIFY_CLIENT_ID", "SHOPIFY_CLIENT_SECRET", "SHOPIFY_WEBHOOK_SECRET"],
        "next_steps": [
            "在 Shopify Partner 后台创建应用，填写上面的回调地址",
            "把 Client ID / Secret 配置到部署环境的环境变量中（不要提交进版本库）",
            "由店铺管理员完成授权后，才能进入 V2 的订单同步阶段",
        ],
    },
    "amazon": {
        "display_name": "Amazon SP-API",
        "auth_type": "LWA（Login with Amazon）+ SP-API",
        "required_scopes": ["sellingpartnerapi::orders", "sellingpartnerapi::notifications"],
        "webhook_callback_path": "/api/integrations/webhook/amazon",
        "env_var_names": ["AMAZON_LWA_CLIENT_ID", "AMAZON_LWA_CLIENT_SECRET", "AMAZON_ROLE_ARN"],
        "next_steps": [
            "在 Seller Central 注册开发者并申请 SP-API 角色",
            "把 LWA 凭证配置到部署环境的环境变量中",
            "通过卖家授权流程拿到 refresh token 后，才能进入 V2 的订单同步阶段",
        ],
    },
    "tiktok_shop": {
        "display_name": "TikTok Shop",
        "auth_type": "OAuth 2.0（Shop Authorization）",
        "required_scopes": ["order.info", "logistics.info", "return.info"],
        "webhook_callback_path": "/api/integrations/webhook/tiktok_shop",
        "env_var_names": ["TIKTOK_APP_KEY", "TIKTOK_APP_SECRET", "TIKTOK_WEBHOOK_SECRET"],
        "next_steps": [
            "在 TikTok Shop Partner Center 创建应用并登记回调地址",
            "把 App Key / Secret 配置到部署环境的环境变量中",
            "由店铺完成授权后，才能进入 V2 的订单同步阶段",
        ],
    },
}

_NOTICE = "这是自动生成的接入配置清单，不代表已连接真实店铺；本系统不会发起任何外部请求。"


@router.get("/providers/{provider}/blueprint", response_model=ProviderBlueprint)
def get_blueprint(provider: str) -> ProviderBlueprint:
    """自动接入：按平台生成接入清单。纯本地模板，无网络调用。"""
    tpl = _BLUEPRINTS.get(provider)
    if tpl is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="不支持的平台")
    return ProviderBlueprint(provider=provider, notice=_NOTICE, **tpl)


@router.get("", response_model=list[IntegrationDraftOut])
def list_drafts(
    user: User = Depends(require_admin), db: Session = Depends(get_db)
) -> list[IntegrationDraftOut]:
    rows = db.scalars(
        select(IntegrationConfig)
        .where(IntegrationConfig.tenant_id == user.tenant_id)
        .order_by(IntegrationConfig.id.desc())
    )
    return [IntegrationDraftOut.model_validate(r) for r in rows]


@router.post("", response_model=IntegrationDraftOut, status_code=status.HTTP_201_CREATED)
def create_draft(
    payload: IntegrationDraftCreate,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> IntegrationDraftOut:
    row = IntegrationConfig(
        tenant_id=user.tenant_id,
        provider=payload.provider,
        mode=payload.mode,
        store_identifier=payload.store_identifier,
        region=payload.region,
        requested_scopes=payload.requested_scopes,
        status="draft",  # 唯一取值；不接受调用方指定
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="该平台下同一店铺标识已有草稿"
        ) from None

    # 审计只记结构化元数据；store_identifier 也不写，它可能是客户的真实域名。
    audit.record(
        db,
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action="integration.draft_created",
        object_type="integration_config",
        object_id=row.id,
    )
    db.commit()
    return IntegrationDraftOut.model_validate(row)


def _load_own(db: Session, user: User, config_id: int) -> IntegrationConfig:
    row = db.scalar(
        select(IntegrationConfig).where(
            IntegrationConfig.id == config_id,
            IntegrationConfig.tenant_id == user.tenant_id,
        )
    )
    if row is None:
        # 跨租户与不存在返回同一个 404，不泄露"这个 id 存在但不属于你"
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="接入草稿不存在")
    return row


@router.get("/{config_id}", response_model=IntegrationDraftOut)
def get_draft(
    config_id: int, user: User = Depends(require_admin), db: Session = Depends(get_db)
) -> IntegrationDraftOut:
    return IntegrationDraftOut.model_validate(_load_own(db, user, config_id))


@router.delete("/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_draft(
    config_id: int, user: User = Depends(require_admin), db: Session = Depends(get_db)
) -> None:
    row = _load_own(db, user, config_id)
    db.delete(row)
    audit.record(
        db,
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action="integration.draft_deleted",
        object_type="integration_config",
        object_id=config_id,
    )
    db.commit()


# 供测试断言：接口层声明的字段里不得出现任何凭证名。
# 放在模块内而非测试内，是为了让这条约束跟着实现走——
# 以后有人往 IntegrationDraftCreate 加字段，测试会立刻炸。
def declared_request_fields() -> set[str]:
    return set(IntegrationDraftCreate.model_fields)


def credential_field_names() -> set[str]:
    return set(_CREDENTIAL_FIELDS)
