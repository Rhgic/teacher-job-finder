"""接入中心（V1.1）API 与权限测试。

重点不是"能不能建草稿"，而是**这个模块承诺不做的事真的做不到**：
不收凭证、不越权、不跨租户、不存在 connected。
"""

import pytest
from sqlalchemy import select

from app.models import IntegrationConfig, Tenant, User
from app.routers.auth import ROLE_ADMIN, hash_password
from app.routers.integrations import credential_field_names, declared_request_fields

_DRAFT = {
    "provider": "shopify",
    "mode": "manual",
    "store_identifier": "demo-shop.myshopify.com",
    "region": "US",
    "requested_scopes": ["read_orders"],
}


# ── admin CRUD ────────────────────────────────────────────────────
def test_admin_can_create_list_get_delete_draft(client, admin_headers):
    created = client.post("/api/integrations", json=_DRAFT, headers=admin_headers)
    assert created.status_code == 201
    body = created.json()
    assert body["status"] == "draft"
    assert body["provider"] == "shopify"
    config_id = body["id"]

    listed = client.get("/api/integrations", headers=admin_headers)
    assert listed.status_code == 200
    assert any(x["id"] == config_id for x in listed.json())

    fetched = client.get(f"/api/integrations/{config_id}", headers=admin_headers)
    assert fetched.status_code == 200

    assert client.delete(f"/api/integrations/{config_id}", headers=admin_headers).status_code == 204
    assert client.get(f"/api/integrations/{config_id}", headers=admin_headers).status_code == 404


def test_status_can_only_be_draft(client, admin_headers):
    """不存在 connected：调用方指定 status 会被 extra="forbid" 拒绝，
    即使绕过接口，库里也有 CHECK 约束兜底。"""
    payload = {**_DRAFT, "store_identifier": "s2.myshopify.com", "status": "connected"}
    assert client.post("/api/integrations", json=payload, headers=admin_headers).status_code == 422


def test_duplicate_store_per_provider_conflicts(client, admin_headers):
    p = {**_DRAFT, "store_identifier": "dup.myshopify.com"}
    assert client.post("/api/integrations", json=p, headers=admin_headers).status_code == 201
    assert client.post("/api/integrations", json=p, headers=admin_headers).status_code == 409


# ── 权限 ──────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/integrations"),
        ("post", "/api/integrations"),
        ("get", "/api/integrations/1"),
        ("delete", "/api/integrations/1"),
        ("get", "/api/integrations/providers/shopify/blueprint"),
    ],
)
def test_agent_is_forbidden_everywhere(client, agent_headers, method, path):
    """agent 对每一个端点都是 403。

    前端不显示入口只是体验；后端拒绝才是权限——前端藏起来的东西，
    任何人用 curl 都能直接打到。
    """
    kwargs = {"json": _DRAFT} if method == "post" else {}
    response = getattr(client, method)(path, headers=agent_headers, **kwargs)
    assert response.status_code == 403


def test_unauthenticated_is_rejected(client):
    assert client.get("/api/integrations").status_code == 401


# ── 跨租户 ────────────────────────────────────────────────────────
def test_cross_tenant_access_returns_404(client, admin_headers, db):
    """别家租户的草稿一律 404——不能是 403，那等于确认了"这个 id 存在"。"""
    other = Tenant(name="另一家店（测试）", slug="other-shop-test")
    db.add(other)
    db.flush()
    db.add(
        User(
            tenant_id=other.id,
            username="other-admin",
            password_hash=hash_password("x" * 12),
            role=ROLE_ADMIN,
            is_active=True,
        )
    )
    foreign = IntegrationConfig(
        tenant_id=other.id,
        provider="amazon",
        mode="manual",
        store_identifier="foreign-store",
        region="EU",
        requested_scopes=[],
        status="draft",
    )
    db.add(foreign)
    db.commit()

    assert client.get(f"/api/integrations/{foreign.id}", headers=admin_headers).status_code == 404
    deleted = client.delete(f"/api/integrations/{foreign.id}", headers=admin_headers)
    assert deleted.status_code == 404
    # 列表里也不能出现别家的
    listed = client.get("/api/integrations", headers=admin_headers).json()
    assert all(x["id"] != foreign.id for x in listed)


# ── 凭证绝不进入系统 ───────────────────────────────────────────────
@pytest.mark.parametrize(
    "field",
    ["api_key", "access_token", "client_secret", "token", "refresh_token", "app_secret"],
)
def test_credential_fields_are_rejected(client, admin_headers, field):
    """带任何凭证字段的请求必须 422，而不是"忽略掉然后照常创建"。

    静默忽略最危险：调用方以为传成功了，凭证可能已经躺在日志或代理缓存里。
    """
    payload = {
        **_DRAFT,
        "store_identifier": f"cred-{field}.myshopify.com",
        field: "s3cr3t-value",
    }
    response = client.post("/api/integrations", json=payload, headers=admin_headers)
    assert response.status_code == 422
    # 报错信息里不得回显传进来的值
    assert "s3cr3t-value" not in response.text


def test_request_model_declares_no_credential_fields():
    """接口层字段名与凭证名零交集。

    这条测试跟着实现走：以后有人往 IntegrationDraftCreate 加了 access_token，
    这里立刻炸，而不是等到凭证已经落库才发现。
    """
    assert declared_request_fields() & credential_field_names() == set()


def test_no_credentials_persisted(client, admin_headers, db):
    """表结构本身没有凭证列——写不进来就漏不出去。"""
    client.post(
        "/api/integrations",
        json={**_DRAFT, "store_identifier": "persist-check.myshopify.com"},
        headers=admin_headers,
    )
    row = db.scalar(
        select(IntegrationConfig).where(
            IntegrationConfig.store_identifier == "persist-check.myshopify.com"
        )
    )
    assert row is not None
    columns = set(IntegrationConfig.__table__.columns.keys())
    assert columns & credential_field_names() == set()


# ── 自动接入清单：纯本地模板，不发外部请求 ──────────────────────────
@pytest.mark.parametrize("provider", ["shopify", "amazon", "tiktok_shop"])
def test_blueprint_is_local_and_marked_not_connected(client, admin_headers, provider):
    response = client.get(
        f"/api/integrations/providers/{provider}/blueprint", headers=admin_headers
    )
    assert response.status_code == 200
    data = response.json()
    assert data["provider"] == provider
    assert data["required_scopes"] and data["env_var_names"] and data["next_steps"]
    # 措辞必须说清这只是生成配置，不是已连接
    assert "不代表已连接真实店铺" in data["notice"]
    # 只给环境变量名，不给值
    assert all("=" not in name for name in data["env_var_names"])


def test_unknown_provider_returns_404(client, admin_headers):
    assert (
        client.get("/api/integrations/providers/ebay/blueprint", headers=admin_headers).status_code
        == 404
    )


def test_no_connectivity_test_endpoint_exists(client, admin_headers):
    """刻意不提供任何"测试连接"端点：没有出口就没有 SSRF。

    这比维护 URL 白名单可靠——白名单会被后人放宽，不存在的端点不会。
    """
    for path in ("/api/integrations/test", "/api/integrations/verify", "/api/integrations/ping"):
        assert client.post(path, json={"url": "http://169.254.169.254/"},
                           headers=admin_headers).status_code in (404, 405)
