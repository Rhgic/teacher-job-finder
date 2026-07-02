"""RAG index builder: job notices -> chunks -> embeddings -> SQLite."""
from __future__ import annotations

import json
import re

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from models import DocChunk, Job
from services.embedding import embed

MAX_CHARS = 500
MIN_CHARS = 180


def _normalize_text(text: str) -> str:
    lines = [re.sub(r"\s+", " ", line).strip() for line in (text or "").splitlines()]
    return "\n".join(line for line in lines if line)


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[。！？!?；;])\s*|\n+", text)
    return [item.strip() for item in parts if item and item.strip()]


def chunk_text(text: str) -> list[str]:
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
            chunks.append("\n".join(current).strip())
            overlap = current[-1]
            current = [overlap, sentence]
            current_len = len(overlap) + len(sentence)
            continue

        current.append(sentence)
        current_len += len(sentence)

        if current_len >= MAX_CHARS:
            chunks.append("\n".join(current).strip())
            overlap = current[-1]
            current = []
            current_len = 0

    if current:
        chunk = "\n".join(current).strip()
        if chunk and (not chunks or chunk != chunks[-1]):
            chunks.append(chunk)

    return [chunk for chunk in chunks if chunk]


def _job_notice_text(job: Job) -> str:
    parts = [
        f"岗位标题：{job.title}",
        f"学校：{job.school_name}",
        f"区域：{job.district}",
        f"学段：{job.stage}",
        f"学科：{job.subject}",
        f"招聘人数：{job.headcount or '未注明'}",
        f"是否编制：{'有编制' if job.has_bianzhi else '未标注编制'}",
        f"薪资：{job.salary_min or '-'}-{job.salary_max or '-'}",
        f"投递邮箱：{job.apply_email or '未注明'}",
        f"截止时间：{job.deadline_at.isoformat() if job.deadline_at else '未注明'}",
        f"公告原文：{job.jd}",
    ]
    return "\n".join(parts)


def reindex(db: Session) -> dict[str, int]:
    db.execute(delete(DocChunk))

    jobs = db.scalars(
        select(Job).order_by(Job.published_at.desc().nullslast(), Job.created_at.desc())
    ).all()
    pending: list[tuple[Job, int, str]] = []
    for job in jobs:
        for index, content in enumerate(chunk_text(_job_notice_text(job))):
            pending.append((job, index, content))

    if not pending:
        db.commit()
        return {"chunks": 0, "jobs": len(jobs)}

    vectors = embed([content for _, _, content in pending])
    for (job, index, content), vector in zip(pending, vectors, strict=True):
        db.add(
            DocChunk(
                source_type="job",
                source_id=job.id,
                source_title=job.title,
                content=content,
                chunk_index=index,
                embedding=json.dumps(vector, ensure_ascii=False),
            )
        )

    db.commit()
    return {"chunks": len(pending), "jobs": len(jobs)}
