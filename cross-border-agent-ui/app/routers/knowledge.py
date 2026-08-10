"""知识库查询：给客服在工作台里手动查政策用。"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.routers.auth import get_current_user
from app.schemas import ArticleOut, KbSearchResponse
from app.services import retrieval

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


@router.get("/search", response_model=KbSearchResponse)
def search(
    q: str = Query(min_length=1, max_length=200),
    lang: str = Query(default="en", max_length=8),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> KbSearchResponse:
    hits = retrieval.search(db, user.tenant_id, q, lang=lang)
    return KbSearchResponse(
        query=q,
        hits=[ArticleOut(id=h.article_id, title=h.title, body=h.body, lang=h.lang) for h in hits],
    )
