"""RAG question answering over indexed job notice chunks."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from config import settings
from models import DocChunk
from services.embedding import embed

MIN_SCORE = 0.08
DEFAULT_TOP_K = 3
NOT_FOUND_ANSWER = "提供的公告未提及该信息，建议查看公告原文。"
QUERY_STOP_CHARS = set("吗呢么啊呀吧的了和与及或是有无要需请问哪些什么是否一个这个那个")
MISSING_VALUES = {"", "-", "未注明", "未标注", "未标注编制"}

FIELD_INTENTS = (
    (("邮箱", "投递方式", "怎么投", "如何投"), "投递邮箱"),
    (("截止", "报名时间", "报名日期"), "截止时间"),
    (("编制",), "是否编制"),
    (("薪资", "工资", "待遇"), "薪资"),
    (("人数", "招几", "招聘几"), "招聘人数"),
    (("区域", "哪里", "地点"), "区域"),
    (("学段",), "学段"),
    (("学科", "科目"), "学科"),
)
GENERAL_REQUIREMENT_KEYWORDS = ("要求", "条件", "经验")
SPECIFIC_REQUIREMENT_KEYWORDS = ("资格", "证书", "普通话", "学历", "学位")

SYSTEM_PROMPT = """你是教师招聘公告问答助手。只能依据【提供的公告片段】回答用户问题。
规则：
- 答案必须有据可查，并标注信息来自哪条公告。
- 公告片段中没有的信息，绝不编造、绝不推测；直接回复“提供的公告未提及该信息，建议查看公告原文。”
- 报考资格、截止日期、材料要求等关键信息，引用原文，不改写数字与日期。
- 简体中文，简洁作答，不使用 Markdown 符号。"""


@dataclass(frozen=True)
class RetrievedChunk:
    content: str
    source_title: str
    source_id: str
    score: float


def _dot(left: list[float], right: list[float]) -> float:
    return sum(x * y for x, y in zip(left, right, strict=False))


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
    terms = {compact[i : i + 2] for i in range(len(compact) - 1)}
    terms = {term for term in terms if not all(ch in QUERY_STOP_CHARS for ch in term)}
    for word in (
        "材料",
        "报名",
        "截止",
        "资格",
        "证书",
        "教师资格证",
        "普通话",
        "学历",
        "学位",
        "邮箱",
        "薪资",
        "编制",
        "人数",
        "区域",
    ):
        if word in compact:
            terms.add(word)
    return terms


def _passes_stub_lexical_gate(question: str, content: str) -> bool:
    terms = _query_terms(question)
    if not terms:
        return False
    return any(term in content for term in terms)


def _school_name(content: str) -> str:
    return _extract_field(content, "学校") or ""


def _question_mentions_known_school(question: str, chunks: list[DocChunk]) -> bool:
    return any(_school_name(chunk.content) in question for chunk in chunks if _school_name(chunk.content))


def retrieve(db: Session, question: str, k: int = DEFAULT_TOP_K) -> list[RetrievedChunk]:
    query = (question or "").strip()
    if not query:
        return []
    query_vector = embed([query])[0]
    all_chunks = db.scalars(select(DocChunk)).all()
    school_scoped = [
        chunk for chunk in all_chunks
        if (_school_name(chunk.content) and _school_name(chunk.content) in query)
        or (chunk.source_title and chunk.source_title in query)
    ]
    candidates = school_scoped or all_chunks

    scored: list[RetrievedChunk] = []
    for chunk in candidates:
        if settings.EMBEDDING_STUB_MODE and not _passes_stub_lexical_gate(query, chunk.content):
            continue
        vector = _load_embedding(chunk.embedding)
        if not vector:
            continue
        score = _dot(query_vector, vector)
        if score < MIN_SCORE:
            continue
        scored.append(
            RetrievedChunk(
                content=chunk.content,
                source_title=chunk.source_title or "未命名公告",
                source_id=chunk.source_id,
                score=score,
            )
        )

    scored.sort(key=lambda item: item.score, reverse=True)
    if not scored:
        return []
    if school_scoped:
        return scored[: max(1, k)]

    relative_floor = max(MIN_SCORE, scored[0].score * 0.72)
    return [item for item in scored if item.score >= relative_floor][: max(1, k)]


def build_user_prompt(question: str, chunks: list[RetrievedChunk]) -> str:
    parts = ["【公告片段】"]
    for index, chunk in enumerate(chunks, start=1):
        parts.append(
            f"{index}. 出处标题：{chunk.source_title}\n"
            f"相似度：{chunk.score:.4f}\n"
            f"片段：{chunk.content}"
        )
    parts.append(f"\n【用户问题】\n{question.strip()}")
    return "\n\n".join(parts)


def _sources(chunks: list[RetrievedChunk]) -> list[dict]:
    return [
        {
            "source_id": chunk.source_id,
            "title": chunk.source_title,
            "snippet": chunk.content[:180],
            "score": round(chunk.score, 4),
        }
        for chunk in chunks
    ]


def _extract_field(content: str, label: str) -> str | None:
    match = re.search(rf"{re.escape(label)}：([^\n]+)", content)
    if not match:
        return None
    value = match.group(1).strip()
    return value if value else None


def _question_field(question: str) -> str | None:
    question_text = question.strip()
    for keywords, label in FIELD_INTENTS:
        if any(keyword in question_text for keyword in keywords):
            return label
    return None


def _format_field_value(label: str, value: str) -> str:
    if label == "截止时间":
        match = re.match(r"(\d{4})-(\d{2})-(\d{2})", value)
        if match:
            return f"{match.group(1)}年{int(match.group(2))}月{int(match.group(3))}日"
    return value


def _plain_text(answer: str) -> str:
    text = answer.strip()
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = text.replace("`", "")
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)
    return text


def _stub_answer(question: str, chunks: list[RetrievedChunk]) -> str | None:
    first = chunks[0]
    question_text = question.strip()
    label = _question_field(question_text)
    if label:
        value = _extract_field(first.content, label)
        if value and value not in MISSING_VALUES:
            value = _format_field_value(label, value)
            return f"根据《{first.source_title}》，{label}：{value}。请以公告原文为准。"
        return None

    if any(keyword in question_text for keyword in GENERAL_REQUIREMENT_KEYWORDS):
        value = _extract_field(first.content, "公告原文")
        if value and value not in MISSING_VALUES:
            return f"根据《{first.source_title}》，公告中的岗位要求为：{value}。请以公告原文为准。"
    if any(keyword in question_text for keyword in SPECIFIC_REQUIREMENT_KEYWORDS):
        value = _extract_field(first.content, "公告原文")
        asked_keywords = [keyword for keyword in SPECIFIC_REQUIREMENT_KEYWORDS if keyword in question_text]
        if value and any(keyword in value for keyword in asked_keywords):
            return f"根据《{first.source_title}》，公告原文写明：{value}。请以公告原文为准。"
    return None


def _call_deepseek_chat(system_prompt: str, user_prompt: str, timeout: int = 40) -> str:
    if not settings.DEEPSEEK_API_KEY:
        raise RuntimeError("DEEPSEEK_API_KEY is not configured")

    response = httpx.post(
        f"{settings.DEEPSEEK_BASE_URL.rstrip('/')}/chat/completions",
        headers={
            "Authorization": f"Bearer {settings.DEEPSEEK_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": settings.DEEPSEEK_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.1,
        },
        timeout=timeout,
    )
    response.raise_for_status()
    data = response.json()
    return str(data["choices"][0]["message"]["content"])


def ask(
    db: Session,
    question: str,
    k: int = DEFAULT_TOP_K,
    context_title: str | None = None,
) -> dict:
    all_chunks = db.scalars(select(DocChunk)).all()
    retrieval_question = question.strip()
    if context_title and not _question_mentions_known_school(retrieval_question, all_chunks):
        retrieval_question = f"{context_title} {retrieval_question}"

    chunks = retrieve(db, retrieval_question, k=k)
    if not chunks:
        return {"answer": NOT_FOUND_ANSWER, "found": False, "sources": []}

    sources = _sources(chunks)
    if settings.LLM_STUB_MODE:
        answer = _stub_answer(question, chunks)
        if not answer:
            return {"answer": NOT_FOUND_ANSWER, "found": False, "sources": []}
        return {"answer": answer, "found": True, "sources": sources}

    user_prompt = build_user_prompt(question, chunks)
    try:
        answer = _plain_text(_call_deepseek_chat(SYSTEM_PROMPT, user_prompt))
    except Exception as exc:  # noqa: BLE001
        answer = _stub_answer(question, chunks) or ""
    if not answer or "未提及" in answer:
        return {"answer": NOT_FOUND_ANSWER, "found": False, "sources": []}
    return {"answer": answer, "found": True, "sources": sources}
