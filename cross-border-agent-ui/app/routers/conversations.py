"""会话、消息、AI 草稿、采纳。

所有查询都以 current_user.tenant_id 起手——这是多租户隔离的唯一防线，
少写一次 where 就是一次跨店泄露。
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Conversation, Draft, KnowledgeArticle, Message, Order, User
from app.routers.auth import get_current_user
from app.schemas import (
    AcceptDraftResponse,
    AgentTraceStepOut,
    ArticleOut,
    ConversationDetail,
    ConversationOut,
    CreateMessageRequest,
    CreateMessageResponse,
    DraftOut,
    MessageOut,
    OrderOut,
)
from app.services import agent, audit
from app.services.risk import risk_type_label

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


def _order_out(order: Order | None) -> OrderOut | None:
    if order is None:
        return None
    return OrderOut(
        id=order.id,
        order_no=order.order_no,
        platform=order.platform,
        country=order.country,
        status=order.status,
        shipping_summary=order.shipping_summary,
        logistics_steps=order.logistics_steps or [],
        amount_display=f"{order.currency} {order.amount:.2f}",
    )


def _conversation_out(db: Session, conv: Conversation) -> ConversationOut:
    order = db.get(Order, conv.order_id) if conv.order_id else None
    return ConversationOut(
        id=conv.id,
        buyer_name=conv.buyer_name,
        lang=conv.lang,
        status=conv.status,
        order=_order_out(order),
        created_at=conv.created_at,
    )


def _load_conversation(db: Session, tenant_id: int, conversation_id: int) -> Conversation:
    conv = db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id, Conversation.tenant_id == tenant_id
        )
    )
    if conv is None:
        # 跨租户访问与不存在返回同一个 404，不泄露"这个 id 存在但不属于你"
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
    return conv


@router.get("", response_model=list[ConversationOut])
def list_conversations(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[ConversationOut]:
    convs = db.scalars(
        select(Conversation)
        .where(Conversation.tenant_id == user.tenant_id)
        .order_by(Conversation.id.desc())
    )
    return [_conversation_out(db, c) for c in convs]


@router.get("/{conversation_id}", response_model=ConversationDetail)
def get_conversation(
    conversation_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ConversationDetail:
    conv = _load_conversation(db, user.tenant_id, conversation_id)
    messages = db.scalars(
        select(Message)
        .where(Message.tenant_id == user.tenant_id, Message.conversation_id == conv.id)
        .order_by(Message.id)
    )
    drafts = db.scalars(
        select(Draft)
        .where(Draft.tenant_id == user.tenant_id, Draft.conversation_id == conv.id)
        .order_by(Draft.id)
    )
    return ConversationDetail(
        conversation=_conversation_out(db, conv),
        messages=[MessageOut.model_validate(m) for m in messages],
        drafts=[DraftOut.model_validate(d) for d in drafts],
    )


@router.post("/{conversation_id}/messages", response_model=CreateMessageResponse)
async def create_message(
    conversation_id: int,
    payload: CreateMessageRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CreateMessageResponse:
    """录入一条买家消息并跑完整条管道。"""
    conv = _load_conversation(db, user.tenant_id, conversation_id)

    outcome = await agent.process_buyer_message(
        db,
        tenant_id=user.tenant_id,
        conversation=conv,
        raw_text=payload.text,
        actor_id=user.id,
    )
    db.commit()

    cited = []
    if outcome.citations:
        cited = list(
            db.scalars(
                select(KnowledgeArticle).where(
                    KnowledgeArticle.tenant_id == user.tenant_id,
                    KnowledgeArticle.id.in_(outcome.citations),
                )
            )
        )

    return CreateMessageResponse(
        run_id=outcome.run_id,
        message=MessageOut.model_validate(outcome.message),
        draft=DraftOut.model_validate(outcome.draft),
        citations=[ArticleOut.model_validate(a) for a in cited],
        agent_trace=[
            AgentTraceStepOut(
                stage=step.stage,
                status=step.status,
                summary=step.summary,
                meta=step.meta,
            )
            for step in outcome.trace
        ],
        human_review_required=outcome.human_review_required,
        risk_type=risk_type_label(outcome.risk_type) if outcome.risk_type else None,
        review_task_id=outcome.review_task.id if outcome.review_task else None,
    )


@router.post("/{conversation_id}/drafts/{draft_id}/accept", response_model=AcceptDraftResponse)
def accept_draft(
    conversation_id: int,
    draft_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AcceptDraftResponse:
    """客服采纳低风险草稿。

    高风险草稿在这里被硬拦：即使前端出 bug 把按钮画出来了，接口也不放行。
    """
    _load_conversation(db, user.tenant_id, conversation_id)
    draft = db.scalar(
        select(Draft).where(
            Draft.id == draft_id,
            Draft.tenant_id == user.tenant_id,
            Draft.conversation_id == conversation_id,
        )
    )
    if draft is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="草稿不存在")

    if draft.risk_level == "high" or draft.status == "blocked":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="高风险草稿必须经管理员审批，不能直接采纳",
        )
    if draft.status == "accepted":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该草稿已采纳")

    draft.status = "accepted"
    audit.record(
        db,
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action="draft.accepted",
        object_type="draft",
        object_id=draft.id,
        meta={
            "conversation_id": conversation_id,
            "risk_level": draft.risk_level,
            "generator": draft.generator,
        },
    )
    db.commit()
    return AcceptDraftResponse(draft=DraftOut.model_validate(draft))
