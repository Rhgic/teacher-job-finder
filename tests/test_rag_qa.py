import json

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from database import Base
from models import DocChunk
from services import rag_qa
from services.embedding import embed


def notice(school: str, title: str, deadline: str, establishment: str = "有编制") -> str:
    return "\n".join(
        [
            f"岗位标题：{title}",
            f"学校：{school}",
            "区域：罗湖区",
            "学段：初中",
            "学科：化学",
            "招聘人数：1",
            f"是否编制：{establishment}",
            "薪资：16000-25000",
            "投递邮箱：hr@example.edu.cn",
            f"截止时间：{deadline}",
            f"公告原文：{school}招聘教师，要求具备相关教学经验。",
        ]
    )


def add_chunk(db: Session, source_id: str, title: str, content: str) -> None:
    db.add(
        DocChunk(
            source_type="job",
            source_id=source_id,
            source_title=title,
            content=content,
            chunk_index=0,
            embedding=json.dumps(embed([content])[0]),
        )
    )


def build_db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    add_chunk(
        db,
        "job-cuiyuan",
        "翠园东晓中学初中化学教师招聘",
        notice(
            "翠园东晓中学",
            "翠园东晓中学初中化学教师招聘",
            "2026-07-20T12:00:00",
        ),
    )
    add_chunk(
        db,
        "job-other",
        "其他学校初中化学教师招聘",
        notice(
            "其他学校",
            "其他学校初中化学教师招聘",
            "2026-07-25T12:00:00",
            establishment="未标注编制",
        ),
    )
    db.commit()
    return db


def test_exact_school_question_only_returns_that_school(monkeypatch) -> None:
    monkeypatch.setattr(rag_qa.settings, "LLM_STUB_MODE", True)
    monkeypatch.setattr(rag_qa.settings, "EMBEDDING_STUB_MODE", True)
    db = build_db()
    try:
        result = rag_qa.ask(db, "翠园东晓中学这个岗位有编制吗？")
    finally:
        db.close()

    assert result["found"] is True
    assert len(result["sources"]) == 1
    assert result["sources"][0]["source_id"] == "job-cuiyuan"


def test_unknown_field_is_rejected_even_when_school_matches(monkeypatch) -> None:
    monkeypatch.setattr(rag_qa.settings, "LLM_STUB_MODE", True)
    monkeypatch.setattr(rag_qa.settings, "EMBEDDING_STUB_MODE", True)
    db = build_db()
    try:
        result = rag_qa.ask(db, "翠园东晓中学提供宿舍吗？")
    finally:
        db.close()

    assert result == {
        "answer": rag_qa.NOT_FOUND_ANSWER,
        "found": False,
        "sources": [],
    }


def test_follow_up_uses_previous_source_context(monkeypatch) -> None:
    monkeypatch.setattr(rag_qa.settings, "LLM_STUB_MODE", True)
    monkeypatch.setattr(rag_qa.settings, "EMBEDDING_STUB_MODE", True)
    db = build_db()
    try:
        result = rag_qa.ask(
            db,
            "那截止到什么时候？",
            context_title="翠园东晓中学初中化学教师招聘",
        )
    finally:
        db.close()

    assert result["found"] is True
    assert "2026年7月20日" in result["answer"]
    assert result["sources"][0]["source_id"] == "job-cuiyuan"
