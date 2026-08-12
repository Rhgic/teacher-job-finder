"""RAG 招聘公告问答：检索公告片段 + 防幻觉回答。"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from config import settings
from models import DocChunk
from services import ratelimit
from services.embedding import embed
from services.llm_credentials import LLMCredential
from services.llm_match import _call_deepseek

logger = logging.getLogger("rag")

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


def _passes_stub_lexical_gate(question: str, content: str, extra_terms: set[str] | None = None) -> bool:
    """占位向量较粗糙，额外要求问题关键词在片段中出现，避免无关问题误命中。"""
    terms = _query_terms(question) | (extra_terms or set())
    if not terms:
        return False
    return any(term in content for term in terms)


EXPAND_PROMPT = """你把求职者的口语提问，翻译成招聘公告里会出现的书面表达。

只输出关键词，用顿号分隔，不要解释、不要编号、不超过 8 个。
关键词要是公告正文里可能原样出现的词，不要输出问句。

例：
问：工资多少？
答：薪酬、待遇、年薪、月薪、工资、绩效

问：有编制吗？
答：编制、事业单位、员额、聘用制、在编"""


def expand_query(question: str, *, cred: LLMCredential | None = None) -> set[str]:
    """把口语问法扩展成公告里的书面用词，用于加宽词法召回。

    公告写"薪酬待遇"，用户问"工资多少"；公告写"资格复审"，用户问"要审什么"。
    纯词法召回对这种同义不同词无能为力——实测 12 个口语问题有 7 个零召回。
    这里用 LLM 补上这一层，避免了为语义检索单独引入 embedding 供应商。

    任何一步失败都返回空集合，退回原有的词法召回，不让问答挂掉。
    """
    q = (question or "").strip()
    if not q or cred is None or cred.is_stub:
        return set()

    cache_key = "qx:" + hashlib.sha256(q.encode("utf-8")).hexdigest()[:32]
    cached = ratelimit.cache_get(cache_key)
    if cached is not None:
        return {t for t in cached.split("、") if t}

    try:
        raw = _call_deepseek(EXPAND_PROMPT, f"问：{q}\n答：",
                             cred=cred, json_mode=False)
    except Exception as exc:  # noqa: BLE001 - 扩展失败不该影响主流程
        logger.warning("query_expand_failed", extra={"extra_fields": {"error": str(exc)}})
        return set()

    terms = {
        t.strip() for t in re.split(r"[、,，\s]+", raw.strip())
        # 单字太宽泛会把无关片段全放进来；超长的多半是模型没听话输出了句子
        if 2 <= len(t.strip()) <= 12
    }
    ratelimit.cache_set(cache_key, "、".join(sorted(terms)))
    return terms


def retrieve(db: Session, question: str, k: int = DEFAULT_TOP_K,
             expand: bool = True, *, cred: LLMCredential | None = None) -> list[RetrievedChunk]:
    """全量加载 doc_chunks，用点积近似余弦相似度取 top-k。

    expand=True 时先用 LLM 把口语问法扩展成公告用词再做词法召回，
    显著减少"同义不同词"导致的零召回。
    """
    q = (question or "").strip()
    if not q:
        return []
    q_vec = embed([q])[0]
    # cred 为 None 时 expand_query 直接返回空集：检索照常做，只是不做
    # LLM 查询扩展。检索层本身不该因为「用户没配 Key」而完全不可用。
    extra_terms = expand_query(q, cred=cred) if expand else set()

    all_terms = _query_terms(q) | extra_terms
    scored: list[RetrievedChunk] = []
    skipped_dim = 0
    chunks = db.scalars(select(DocChunk)).all()

    # 曾在这里加过 IDF 加权（压低"多少""什么"这类高频词的权重）。
    # 用 10 个口语问题做过 A/B：等权与 IDF 的 P@1、P@3 完全相同，
    # 在当前 123 片段的规模上测不出收益，故按等权保留、不引入这层复杂度。
    for chunk in chunks:
        if settings.EMBEDDING_STUB_MODE and not _passes_stub_lexical_gate(
                q, chunk.content, extra_terms):
            continue
        vec = _load_embedding(chunk.embedding)
        if not vec:
            continue
        # 切换 embedding 模型/维度后若忘了重建索引，库里still是旧维度向量。
        # 点积会在较短的那条上算完并给出一个"看起来正常"的分数，
        # 检索结果整体错乱却不报错——必须显式跳过并告警。
        if len(vec) != len(q_vec):
            skipped_dim += 1
            continue
        if settings.EMBEDDING_STUB_MODE:
            # 占位模式下真正携带信息的是词法命中，而非哈希特征的点积：
            # 实测"什么时候截止"扩展出正确的词、11 个片段过了门控，
            # 但点积最高仅 0.04，全被 0.08 阈值砍掉。
            # 因此改按命中词数占比打分，点积只作细微的同分决胜。
            matched = sum(1 for t in all_terms if t in chunk.content)
            if matched == 0:
                continue
            score = matched / max(len(all_terms), 1) + _dot(q_vec, vec) * 0.01
        else:
            score = _dot(q_vec, vec)
            if score < MIN_SCORE:
                continue
        scored.append(RetrievedChunk(
            content=chunk.content,
            source_title=chunk.source_title or "未命名公告",
            source_id=chunk.source_id,
            score=score,
        ))

    if skipped_dim:
        logger.warning("embedding_dim_mismatch", extra={"extra_fields": {
            "skipped_chunks": skipped_dim,
            "query_dim": len(q_vec),
            "hint": "embedding 模型或维度已变更，请重建索引：POST /rag/reindex",
        }})

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


def ask(db: Session, question: str, k: int = DEFAULT_TOP_K,
        *, cred: LLMCredential) -> dict:
    """RAG 问答入口。未命中不调用 LLM，避免编造。

    cred 必填：问答花的是用户自己的额度，不能落回服务器全局 Key。
    """
    chunks = retrieve(db, question, k=k, cred=cred)
    if not chunks:
        return {"answer": NOT_FOUND_ANSWER, "found": False, "sources": []}

    sources = _sources(chunks)
    if cred.is_stub:
        return {"answer": _stub_answer(question, chunks), "found": True, "sources": sources}

    user_prompt = build_user_prompt(question, chunks)
    try:
        # 问答要自然语言而非 JSON；json_mode 会因 prompt 不含 "json" 被 DeepSeek 拒掉
        answer = _call_deepseek(SYSTEM_PROMPT, user_prompt,
                                cred=cred, json_mode=False).strip()
    except Exception as exc:  # noqa: BLE001 - 单次问答失败不应导致服务崩溃
        logger.warning("rag_answer_failed", extra={"extra_fields": {
            "error": type(exc).__name__}})
        answer = "公告问答暂时不可用，请稍后重试"
    return {"answer": answer or NOT_FOUND_ANSWER, "found": True, "sources": sources}
