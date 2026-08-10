"""Pydantic 请求/响应模型。

写接口一律经过这里：长度限制、类型校验、以及"响应里只出现该出现的字段"。
直接把 ORM 对象丢出去很容易连带泄露 password_hash 这类字段。
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ── auth ──────────────────────────────────────────────────────────
class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=200)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    role: str
    username: str


class MeResponse(BaseModel):
    id: int
    username: str
    role: str
    tenant_id: int
    tenant_name: str


# ── knowledge ─────────────────────────────────────────────────────
class ArticleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    body: str
    lang: str


class KbSearchResponse(BaseModel):
    query: str
    hits: list[ArticleOut]


# ── conversations ─────────────────────────────────────────────────
class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_no: str
    platform: str
    country: str
    status: str
    shipping_summary: str | None = None
    logistics_steps: list[str] | None = None
    amount_display: str


class ConversationOut(BaseModel):
    id: int
    buyer_name: str
    lang: str
    status: str
    order: OrderOut | None = None
    created_at: datetime


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sender: str
    body: str
    was_redacted: bool
    created_at: datetime


class DraftOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    body: str
    lang: str
    intent: str
    risk_level: str
    status: str
    generator: str
    citations: list[int] = []
    created_at: datetime


class ConversationDetail(BaseModel):
    conversation: ConversationOut
    messages: list[MessageOut]
    drafts: list[DraftOut]


class CreateMessageRequest(BaseModel):
    # 上限与 settings.max_message_chars 保持一致；超长直接 422，不进模型
    text: str = Field(min_length=1, max_length=2000)


class CreateMessageResponse(BaseModel):
    run_id: str
    message: MessageOut
    draft: DraftOut
    citations: list[ArticleOut]
    human_review_required: bool
    risk_type: str | None = None
    review_task_id: int | None = None


class AcceptDraftResponse(BaseModel):
    draft: DraftOut
    # V1 不外发；采纳只是把草稿标为"待发送"的内部记录
    note: str = "已采纳为待发送记录；V1 不对接任何外部消息平台，系统不会实际发送。"


# ── reviews ───────────────────────────────────────────────────────
class ReviewOut(BaseModel):
    id: int
    risk_type: str
    risk_type_label: str
    status: str
    conversation_id: int
    buyer_name: str
    draft_body: str
    draft_id: int
    review_reason: str | None = None
    reviewer: str | None = None
    reviewed_at: datetime | None = None
    created_at: datetime


class ReviewDecisionRequest(BaseModel):
    # 审批必须写理由：没有理由的审批等于没有审计价值
    reason: str = Field(min_length=1, max_length=500)


# ── integrations（接入中心 V1.1）────────────────────────────────────
Provider = Literal["shopify", "amazon", "tiktok_shop"]
IntegrationMode = Literal["manual", "guided"]

# 明确拒收的凭证类字段名。extra="forbid" 已经能挡住所有未声明字段，
# 这份清单是为了给出**可读的错误信息**：直接告诉调用方"本系统不接收凭证"，
# 而不是一句泛泛的 "extra fields not permitted"，免得有人以为换个名字就能传。
_CREDENTIAL_FIELDS = {
    "api_key", "apikey", "access_token", "accesstoken", "refresh_token",
    "client_secret", "clientsecret", "client_id", "secret", "token",
    "password", "private_key", "signature", "app_secret",
}


class IntegrationDraftCreate(BaseModel):
    """创建接入草稿。

    这里**没有任何凭证字段**，且 extra="forbid"：凭证根本进不了请求体，
    也就谈不上落库、写日志或回显。安全边界靠类型定义守住，不靠调用方自觉。
    """

    model_config = ConfigDict(extra="forbid")

    provider: Provider
    mode: IntegrationMode
    store_identifier: str = Field(min_length=1, max_length=120)
    region: str = Field(min_length=1, max_length=40)
    requested_scopes: list[str] = Field(default_factory=list, max_length=30)

    @field_validator("requested_scopes")
    @classmethod
    def _scopes_are_plain(cls, v: list[str]) -> list[str]:
        for s in v:
            if not s or len(s) > 80:
                raise ValueError("权限项长度需在 1-80 之间")
        return v


class IntegrationDraftOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    provider: str
    mode: str
    store_identifier: str
    region: str
    requested_scopes: list[str] = []
    # 恒为 draft。本系统不做 OAuth、不发外部请求，不存在 connected 状态。
    status: str
    created_at: datetime
    updated_at: datetime


class ProviderBlueprint(BaseModel):
    """按平台自动生成的接入清单。

    这是"自动生成接入配置"，**不是已连接真实店铺**：
    内容全部来自本地静态模板，生成过程不发起任何外部请求。
    """

    provider: str
    display_name: str
    auth_type: str
    required_scopes: list[str]
    webhook_callback_path: str
    env_var_names: list[str]
    next_steps: list[str]
    notice: str
