"""RAG 招聘公告问答：检索公告片段 + 防幻觉回答。"""
from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from config import settings
from models import DocChunk
from services.embedding import embed
from services.llm_match import _call_deepseek

MIN_SCORE = 0.08
DEFAULT_TOP_K = 5
NOT_FOUND_ANSWER = "提供的公告未提及该信息，建议查看公告原文。"
QUERY_STOP_CHARS = set("吗呢么啊呀吧的了和与及或是有无要需请问哪些什么是否一个这个那个")

SYSTEM_PROMPT = """你是教师招聘公告问答助手。只能依据【提供的公告片段】回答用户问题。
规则：
- 答案必须有据可查，并标注信息来自哪条公告（用片段提供的出处标题）。
- 公告片段中没有的信息，绝不编造、绝不推测；直接回复
  “提供的公告未提及该信息，建议查看公告原文。”
- 报考资格、截止日期、材料要求等关键信息，引用原文，不改写数字与日期。
- 简体中文，简洁作答。"""


@dataclass
class RetrievedChunk:
    content: str
    source_title: str
    source_id: str
    score: float


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=False))


def _load_embedding(raw: str) -> list[float] | None:
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(data, list):
        return None
    try:
        return [float(item) for item in data]
    except (TypeError, ValueError):
        return None


def _query_terms(question: str) -> set[str]:
    compact = "".join(ch for ch in (question or "").strip() if not ch.isspace())
    terms = {compact[i:i + 2] for i in range(len(compact) - 1)}
    terms = {term for term in terms if not all(ch in QUERY_STOP_CHARS for ch in term)}
    for word in ("材料", "报名", "截止", "资格", "证书", "教师资格证", "普通话", "学历", "学位", "邮箱", "时间"):
        if word in compact:
            terms.add(word)
    return terms


def _passes_stub_lexical_gate(question: str, content: str) -> bool:
    """占位向量较粗糙，额外要求问题关键词在片段中出现，避免无关问题误命中。"""
    terms = _query_terms(question)
    if not terms:
        return False
    return any(term in content for term in terms)


def retrieve(db: Session, question: str, k: int = DEFAULT_TOP_K) -> list[RetrievedChunk]:
    """全量加载 doc_chunks，用点积近似余弦相似度取 top-k。"""
    q = (question or "").strip()
    if not q:
        return []
    q_vec = embed([q])[0]

    scored: list[RetrievedChunk] = []
    chunks = db.scalars(select(DocChunk)).all()
    for chunk in chunks:
        if settings.EMBEDDING_STUB_MODE and not _passes_stub_lexical_gate(q, chunk.content):
            continue
        vec = _load_embedding(chunk.embedding)
        if not vec:
            continue
        score = _dot(q_vec, vec)
        if score < MIN_SCORE:
            continue
        scored.append(RetrievedChunk(
            content=chunk.content,
            source_title=chunk.source_title or "未命名公告",
            source_id=chunk.source_id,
            score=score,
        ))

    scored.sort(key=lambda item: item.score, reverse=True)
    return scored[: max(1, k)]


def build_user_prompt(question: str, chunks: list[RetrievedChunk]) -> str:
    """把命中片段和用户问题拼成 RAG user prompt。"""
    parts = ["【公告片段】"]
    for idx, chunk in enumerate(chunks, start=1):
        parts.append(
            f"{idx}. 出处标题：{chunk.source_title}\n"
            f"相似度：{chunk.score:.4f}\n"
            f"片段：{chunk.content}"
        )
    parts.append(f"\n【用户问题】\n{question.strip()}")
    return "\n\n".join(parts)


def _sources(chunks: list[RetrievedChunk]) -> list[dict]:
    return [
        {
            "title": chunk.source_title,
            "snippet": chunk.content[:160],
            "score": round(chunk.score, 4),
        }
        for chunk in chunks
    ]


def _stub_answer(question: str, chunks: list[RetrievedChunk]) -> str:
    title = chunks[0].source_title if chunks else "命中公告"
    return (
        f"（占位回答）已检索到与“{question.strip()}”相关的公告片段，"
        f"请优先核对《{title}》等出处。真实回答需设 LLM_STUB_MODE=0 后调用 DeepSeek。"
    )


def ask(db: Session, question: str, k: int = DEFAULT_TOP_K) -> dict:
    """RAG 问答入口。未命中不调用 LLM，避免编造。"""
    chunks = retrieve(db, question, k=k)
    if not chunks:
        return {"answer": NOT_FOUND_ANSWER, "found": False, "sources": []}

    sources = _sources(chunks)
    if settings.LLM_STUB_MODE:
        return {"answer": _stub_answer(question, chunks), "found": True, "sources": sources}

    user_prompt = build_user_prompt(question, chunks)
    try:
        answer = _call_deepseek(SYSTEM_PROMPT, user_prompt).strip()
    except Exception as exc:  # noqa: BLE001 - 单次问答失败不应导致服务崩溃
        answer = f"公告问答生成失败：{exc}"
    return {"answer": answer or NOT_FOUND_ANSWER, "found": True, "sources": sources}
