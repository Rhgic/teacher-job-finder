"""店铺知识库检索：关键词打分 + 引用。

打分方式：关键词子串命中 / 标题命中 / 同语种加权 / 意图加权。
语料存在 knowledge_articles 表，且**每次查询都强制带 tenant_id**。

为什么不用向量库：V1 的语料是几十条店铺政策，关键词检索已经够用，
引入嵌入模型和向量库只会增加演示门槛和故障面（详见 ARCHITECTURE.md）。
"""

import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import KnowledgeArticle

TOP_K = 3

# 意图 → 相关关键词，用于加权：物流问题应命中清关政策，退款问题应命中退款政策。
INTENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "logistics": ("物流", "清关", "包裹", "logistics", "customs", "shipping", "track", "delay"),
    "refund": ("退款", "退货", "refund", "return"),
    "settlement": ("结算", "佣金", "settlement", "commission", "回款"),
    "quality": ("质量", "瑕疵", "退换", "quality", "defective", "broken"),
    "coupon": ("优惠券", "折扣", "coupon", "promo", "voucher"),
}


@dataclass(frozen=True)
class Hit:
    article_id: int
    title: str
    body: str
    lang: str
    score: int


def _norm(s: str) -> str:
    return (s or "").lower()


def search(
    db: Session,
    tenant_id: int,
    query: str,
    lang: str = "en",
    intent: str | None = None,
    top: int = TOP_K,
) -> list[Hit]:
    """返回最多 top 条知识条目。查不到就返回空列表——由调用方决定如何安全兜底。"""
    q = _norm(query)
    if not q.strip():
        return []

    stmt = select(KnowledgeArticle).where(
        KnowledgeArticle.tenant_id == tenant_id,  # 租户隔离：任何情况下都不跨店检索
        KnowledgeArticle.is_active.is_(True),
    )
    articles = list(db.scalars(stmt))

    q_tokens = set(re.findall(r"[a-z0-9]+", q))
    intent_kws = INTENT_KEYWORDS.get(intent or "", ())

    hits: list[Hit] = []
    for a in articles:
        score = 0
        for kw in a.keywords or []:
            k = _norm(kw)
            if not k:
                continue
            if k in q or (q_tokens and k in q_tokens):
                score += 3
        if _norm(a.title) and _norm(a.title) in q:
            score += 2
        if intent_kws and any(k in (a.keywords or []) for k in intent_kws):
            score += 2
        # 同语种只能给已经相关的条目加权，不能单独把任何英文/中文文章变成命中。
        # 否则陌生问题会被误判为有政策依据，破坏“无命中就转人工”的安全边界。
        if score > 0 and a.lang == lang:
            score += 1
        if score > 0:
            hits.append(Hit(article_id=a.id, title=a.title, body=a.body, lang=a.lang, score=score))

    hits.sort(key=lambda h: h.score, reverse=True)
    return hits[:top]


def pick_body(hits: list[Hit], lang: str) -> str:
    """优先取与买家同语种的政策正文，避免英文回复里嵌一段中文政策。"""
    if not hits:
        return ""
    same = [h for h in hits if h.lang == lang]
    return (same[0] if same else hits[0]).body
