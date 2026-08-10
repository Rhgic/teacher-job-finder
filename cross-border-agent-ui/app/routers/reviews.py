"""人工审核单：列表、通过、驳回。

审批只有 admin 能做（require_admin）。V1 的审批**不触发任何资金或平台动作**，
它只是把这条诉求的处置结论和责任人记录下来——这正是"人工兜底"该有的样子。
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Conversation, Draft, ReviewTask, User
from app.routers.auth import get_current_user, require_admin
from app.schemas import ReviewDecisionRequest, ReviewOut
from app.services import audit
from app.services.risk import risk_type_label

router = APIRouter(prefix="/api/reviews", tags=["reviews"])


def _to_out(db: Session, task: ReviewTask) -> ReviewOut:
    draft = db.get(Draft, task.draft_id)
    conv = db.get(Conversation, task.conversation_id)
    reviewer = db.get(User, task.reviewer_id) if task.reviewer_id else None
    return ReviewOut(
        id=task.id,
        risk_type=task.risk_type,
        risk_type_label=risk_type_label(task.risk_type),
        status=task.status,
        conversation_id=task.conversation_id,
        buyer_name=conv.buyer_name if conv else "",
        draft_body=draft.body if draft else "",
        draft_id=task.draft_id,
        review_reason=task.review_reason,
        reviewer=reviewer.username if reviewer else None,
        reviewed_at=task.reviewed_at,
        created_at=task.created_at,
    )


@router.get("", response_model=list[ReviewOut])
def list_reviews(
    status_filter: str | None = Query(default=None, alias="status"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ReviewOut]:
    """列表对两个角色都开放——客服要能看到自己那条被转去审核了，
    只是不能审批（审批走下面两个 admin 接口）。"""
    stmt = select(ReviewTask).where(ReviewTask.tenant_id == user.tenant_id)
    if status_filter in ("pending", "approved", "rejected"):
        stmt = stmt.where(ReviewTask.status == status_filter)
    tasks = db.scalars(stmt.order_by(ReviewTask.id.desc()))
    return [_to_out(db, t) for t in tasks]


def _decide(db: Session, user: User, review_id: int, decision: str, reason: str) -> ReviewOut:
    task = db.scalar(
        select(ReviewTask).where(ReviewTask.id == review_id, ReviewTask.tenant_id == user.tenant_id)
    )
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="审核单不存在")
    if task.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"该审核单已处理（{task.status}），不能重复处理",
        )

    task.status = decision
    task.reviewer_id = user.id
    task.review_reason = reason
    task.reviewed_at = datetime.now(UTC)

    draft = db.get(Draft, task.draft_id)
    if draft is not None:
        # 通过 = 允许人工据此回复；驳回 = 该草稿作废。两种都不外发。
        draft.status = "accepted" if decision == "approved" else "rejected"

    audit.record(
        db,
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=f"review.{decision}",
        object_type="review_task",
        object_id=task.id,
        meta={
            "decision": decision,
            "risk_type": task.risk_type,
            "draft_id": task.draft_id,
            "conversation_id": task.conversation_id,
            # 只记理由长度，不记理由正文——审批理由可能含买家信息
            "reason_length": len(reason),
        },
    )
    db.commit()
    return _to_out(db, task)


@router.post("/{review_id}/approve", response_model=ReviewOut)
def approve(
    review_id: int,
    payload: ReviewDecisionRequest,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> ReviewOut:
    return _decide(db, user, review_id, "approved", payload.reason)


@router.post("/{review_id}/reject", response_model=ReviewOut)
def reject(
    review_id: int,
    payload: ReviewDecisionRequest,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> ReviewOut:
    return _decide(db, user, review_id, "rejected", payload.reason)
