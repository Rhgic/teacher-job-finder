import json

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from config import settings
from models import Base, DocChunk, Job
from services.rag_index import chunk_text, reindex


def test_chunk_text_splits_long_notice_with_overlap():
    text = "。".join(f"第{i}句深圳教师招聘公告内容，要求语文教学经验和班主任经历" for i in range(60))

    chunks = chunk_text(text)

    assert len(chunks) > 1
    assert all(chunk.strip() for chunk in chunks)


def test_reindex_writes_json_embeddings(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'teacher_jobs.db'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    text = "。".join(f"深圳教师招聘公告第{i}段，包含岗位要求、报名材料和截止时间" for i in range(80))
    with Session() as db:
        db.add(Job(
            source="test",
            external_id="rag-job-1",
            source_url="https://example.com/jobs/rag-job-1",
            school_name="南山实验学校",
            description=text,
        ))
        db.commit()

        result = reindex(db)
        chunks = db.scalars(select(DocChunk)).all()

    assert result["chunks"] == len(chunks)
    assert result["chunks"] > 1
    vector = json.loads(chunks[0].embedding)
    assert len(vector) == settings.EMBEDDING_DIM
    assert chunks[0].source_type == "job"
    assert chunks[0].source_title == "南山实验学校"
