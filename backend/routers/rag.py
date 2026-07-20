"""RAG 索引管理接口。"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from deps import require_admin_token
from services import rag_index, rag_qa

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
    db: Session = Depends(get_db),
):
    """基于已索引公告片段回答问题；默认 stub 模式不调用真实 LLM。"""
    return rag_qa.ask(db, body.question)
