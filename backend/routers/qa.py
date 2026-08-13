"""公告问答会话。

与旧的一次性 `/rag/ask` 的区别：这里的问答有上下文、能持久化、带出处。
用户换台设备或刷新页面，问过什么、AI 依据哪条公告答的，都还在。

会话隔离：所有查询都以当前登录用户为条件，URL 里虽然有 session_id，
但拿别人的 id 来查会得到 404 而不是别人的会话内容。
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import get_db
from deps import require_registered_user
from models import Job, QAMessage, QASession, User
from services import llm_credentials, rag_qa, ratelimit
from services.llm_errors import raise_for_missing_key

router = APIRouter(prefix="/qa", tags=["qa"])

MAX_QUESTION_LEN = 500


class AskIn(BaseModel):
    question: str
    # 从岗位详情页进来时带上，让回答聚焦到该公告
    job_id: str | None = None

    @field_validator("question")
    @classmethod
    def _check(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("问题不能为空")
        if len(v) > MAX_QUESTION_LEN:
            raise ValueError(f"问题请控制在 {MAX_QUESTION_LEN} 字以内")
        return v


def _session_view(s: QASession, *, with_messages: bool = False) -> dict:
    out = {
        "id": s.id,
        "title": s.title,
        "job_id": s.job_id,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }
    if with_messages:
        out["messages"] = [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "sources": m.sources or [],
                "found": m.found,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in s.messages
        ]
    return out


def _owned_session(db: Session, user: User, session_id: str) -> QASession:
    """按 (id, user_id) 取会话。

    条件里必须带 user_id：只按 id 查再比对所有者，会在忘记比对时
    变成越权读取。把归属写进查询条件，漏不掉。
    """
    s = db.scalar(
        select(QASession).where(
            QASession.id == session_id, QASession.user_id == user.id
        )
    )
    if s is None:
        # 刻意回 404 而不是 403：403 等于告诉对方"这个 id 存在，只是不属于你"，
        # 那本身就是一条信息泄漏。
        raise HTTPException(404, "会话不存在")
    return s


@router.get("/sessions")
def list_sessions(
    db: Session = Depends(get_db),
    user: User = Depends(require_registered_user),
):
    """当前用户的会话列表，最近更新的在前。"""
    rows = db.scalars(
        select(QASession)
        .where(QASession.user_id == user.id)
        .order_by(QASession.updated_at.desc())
        .limit(50)
    ).all()
    return [_session_view(s) for s in rows]


@router.get("/sessions/{session_id}")
def get_session(
    session_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_registered_user),
):
    return _session_view(_owned_session(db, user, session_id), with_messages=True)


@router.delete("/sessions/{session_id}")
def delete_session(
    session_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_registered_user),
):
    """清空当前会话。消息随 cascade 一并删除。"""
    db.delete(_owned_session(db, user, session_id))
    db.commit()
    return {"deleted": True}


@router.post("/ask")
def ask_new(
    body: AskIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_registered_user),
):
    """新开一个会话并提问。"""
    return _ask(body, request, None, db, user)


@router.post("/sessions/{session_id}/ask")
def ask_in_session(
    session_id: str,
    body: AskIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_registered_user),
):
    """在已有会话里继续提问。"""
    return _ask(body, request, session_id, db, user)


def _ask(body: AskIn, request: Request, session_id: str | None,
         db: Session, user: User) -> dict:
    """提问的实际实现。两个入口共用。

    顺序：限流 → 配额 → 凭据 → 检索 → 回答 → 落库。
    凭据放在检索之前：没配 Key 时不该白做一次检索，
    更不该让用户看到一个"检索到了但答不出来"的中间态。
    """
    ip = request.client.host if request.client else ""
    if not ratelimit.check_ip_rate(ip):
        raise HTTPException(429, "请求过于频繁，请稍后再试")

    verdict = ratelimit.check_and_consume_llm_quota(user.id)
    if not verdict.allowed:
        raise HTTPException(429, (
            "今日问答次数已用完，请明天再来"
            if verdict.reason == "user_quota_exceeded"
            else "演示环境今日额度已用完，请明天再来"
        ))

    cred = raise_for_missing_key(lambda: llm_credentials.resolve_for_user(db, user.id))

    if session_id:
        session = _owned_session(db, user, session_id)
    else:
        job_id = body.job_id
        if job_id and db.get(Job, job_id) is None:
            raise HTTPException(404, "岗位不存在")
        session = QASession(
            user_id=user.id,
            job_id=job_id,
            # 标题取第一个问题，列表里好认。截断避免撑破列宽。
            title=body.question[:40],
        )
        db.add(session)
        db.flush()

    db.add(QAMessage(session_id=session.id, role="user", content=body.question))

    # 会话绑定了岗位时，把学校名并进检索词——用户在某个岗位页里问
    # "报名要什么材料"，指的是这条公告，不是全站公告的平均答案。
    query = body.question
    if session.job_id:
        job = db.get(Job, session.job_id)
        if job and job.school_name:
            query = f"{job.school_name} {body.question}"

    result = rag_qa.ask(db, query, cred=cred)

    db.add(QAMessage(
        session_id=session.id,
        role="assistant",
        content=result["answer"],
        sources=result.get("sources") or [],
        found=bool(result.get("found")),
    ))
    # 显式刷新 updated_at：新增子行不会 UPDATE 会话本身，
    # 列名上的 onupdate 不会触发，会话列表的排序就永远停在创建时间。
    session.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    db.refresh(session)

    return {
        "session_id": session.id,
        "answer": result["answer"],
        "sources": result.get("sources") or [],
        "found": bool(result.get("found")),
    }
