"""RAG 索引管理接口。"""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from deps import require_admin_token
from services import rag_index, rag_qa, ratelimit

router = APIRouter(prefix="/rag", tags=["rag"])


class AskIn(BaseModel):
    question: str


@router.post("/reindex")
def reindex_rag(
    _: None = Depends(require_admin_token),
    db: Session = Depends(get_db),
):
    """全量重建招聘公告切片索引。默认占位 embedding，无需外部 Key。"""
    return rag_index.reindex(db)


@router.post("/ask")
def ask_rag(
    body: AskIn,
    request: Request,
    db: Session = Depends(get_db),
):
    """基于已索引公告片段回答问题；默认 stub 模式不调用真实 LLM。

    公开可访问且会调用大模型，因此挂上限流与配额：
    没有这道闸，任何人写个循环就能刷爆 API 余额。
    """
    ip = request.client.host if request.client else ""
    if not ratelimit.check_ip_rate(ip):
        raise HTTPException(429, "请求过于频繁，请稍后再试")

    identity = request.headers.get("authorization", "")[-24:] or ip
    verdict = ratelimit.check_and_consume_llm_quota(identity)
    if not verdict.allowed:
        raise HTTPException(429, (
            "今日问答次数已用完，请明天再来"
            if verdict.reason == "user_quota_exceeded"
            else "演示环境今日额度已用完，请明天再来"
        ))
    return rag_qa.ask(db, body.question)
