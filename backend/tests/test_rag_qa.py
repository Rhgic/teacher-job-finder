from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from models import Base, DocChunk, Job
from services import rag_index, rag_qa


def make_session(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'teacher_jobs.db'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def seed_indexed_job(db):
    description = (
        "南山区第二实验学校招聘小学语文教师。"
        "报名材料包括身份证、教师资格证、普通话证书、学历学位证书和报名表。"
        "材料需按公告要求发送至指定邮箱。"
    ) * 20
    db.add(Job(
        source="test",
        external_id="rag-qa-job-1",
        source_url="https://example.com/jobs/rag-qa-job-1",
        school_name="南山区第二实验学校",
        description=description,
    ))
    db.commit()
    rag_index.reindex(db)


def test_retrieve_returns_expected_job_chunk(tmp_path):
    Session = make_session(tmp_path)
    with Session() as db:
        seed_indexed_job(db)

        chunks = rag_qa.retrieve(db, "报名材料需要准备什么", k=3)

    assert chunks
    assert any(chunk.source_title == "南山区第二实验学校" for chunk in chunks)
    assert any("教师资格证" in chunk.content for chunk in chunks)


def test_ask_not_found_does_not_call_llm(tmp_path, monkeypatch):
    Session = make_session(tmp_path)
    called = {"llm": False}

    def fake_call(system, user):
        called["llm"] = True
        return "不应该调用"

    monkeypatch.setattr(rag_qa, "MIN_SCORE", 2.0)
    monkeypatch.setattr(rag_qa, "_call_deepseek", fake_call)
    monkeypatch.setattr(rag_qa.settings, "LLM_STUB_MODE", False)

    with Session() as db:
        seed_indexed_job(db)
        result = rag_qa.ask(db, "火星基地包住宿吗")

    assert result["found"] is False
    assert "未提及" in result["answer"]
    assert result["sources"] == []
    assert called["llm"] is False


def test_stub_lexical_gate_rejects_unrelated_question(tmp_path):
    Session = make_session(tmp_path)
    with Session() as db:
        seed_indexed_job(db)
        result = rag_qa.ask(db, "火星基地包住宿吗")

    assert result["found"] is False
    assert "未提及" in result["answer"]
    assert result["sources"] == []


def test_build_user_prompt_includes_sources_and_chunks():
    chunks = [
        rag_qa.RetrievedChunk(
            content="报名材料包括教师资格证和学历学位证书。",
            source_title="南山区第二实验学校",
            source_id="job-1",
            score=0.42,
        )
    ]

    prompt = rag_qa.build_user_prompt("要准备哪些材料？", chunks)

    assert "南山区第二实验学校" in prompt
    assert "报名材料包括教师资格证" in prompt
    assert "要准备哪些材料" in prompt


def test_stub_ask_returns_answer_with_real_sources(tmp_path):
    Session = make_session(tmp_path)
    with Session() as db:
        seed_indexed_job(db)
        result = rag_qa.ask(db, "报名材料需要准备什么")

    assert result["found"] is True
    assert "占位回答" in result["answer"]
    assert result["sources"]
    assert result["sources"][0]["title"] == "南山区第二实验学校"
