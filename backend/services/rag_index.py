"""RAG 索引构建：招聘公告切分 → 向量化 → 入库。"""
from __future__ import annotations

import json
import re

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from models import DocChunk, Job
from services.embedding import embed

MAX_CHARS = 500
MIN_CHARS = 300


def _normalize_text(text: str) -> str:
    lines = [re.sub(r"\s+", " ", line).strip() for line in (text or "").splitlines()]
    return "\n".join(line for line in lines if line)


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[。！？!?；;])\s*|\n+", text)
    return [item.strip() for item in parts if item and item.strip()]


def chunk_text(text: str) -> list[str]:
    """把公告文本切成约 300-500 字的块，块间保留 1 句重叠。"""
    normalized = _normalize_text(text)
    if not normalized:
        return []

    sentences = _split_sentences(normalized)
    if not sentences:
        return []

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    overlap = ""

    for sentence in sentences:
        if not current and overlap:
            current.append(overlap)
            current_len = len(overlap)

        would_len = current_len + len(sentence)
        if current and current_len >= MIN_CHARS and would_len > MAX_CHARS:
            chunks.append("".join(current).strip())
            overlap = current[-1]
            current = [overlap, sentence]
            current_len = len(overlap) + len(sentence)
            continue

        current.append(sentence)
        current_len += len(sentence)

        # 单句过长时直接成块，避免超长公告段落撑爆后续 prompt。
        if current_len >= MAX_CHARS:
            chunks.append("".join(current).strip())
            overlap = current[-1]
            current = []
            current_len = 0

    if current:
        chunk = "".join(current).strip()
        if chunk and (not chunks or chunk != chunks[-1]):
            chunks.append(chunk)

    return [chunk for chunk in chunks if chunk]


def reindex(db: Session) -> dict:
    """全量重建岗位公告切片索引。默认占位向量，无需任何外部 Key。"""
    db.execute(delete(DocChunk))

    jobs = db.scalars(select(Job).order_by(Job.crawled_at.desc())).all()
    pending: list[tuple[Job, int, str]] = []
    for job in jobs:
        for idx, content in enumerate(chunk_text(job.description or "")):
            pending.append((job, idx, content))

    if not pending:
        db.commit()
        return {"chunks": 0}

    vectors = embed([content for _, _, content in pending])
    for (job, idx, content), vector in zip(pending, vectors, strict=True):
        db.add(DocChunk(
            source_type="job",
            source_id=job.id,
            source_title=job.school_name,
            content=content,
            chunk_index=idx,
            embedding=json.dumps(vector, ensure_ascii=False),
        ))

    db.commit()
    return {"chunks": len(pending)}
