from dataclasses import replace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from models import Base, Job
from services.crawler import RawJob, content_hash, upsert_jobs


def make_raw_job(**overrides):
    data = {
        "source": "test_source",
        "external_id": "job-1",
        "source_url": "https://example.com/jobs/1",
        "school_name": "南山实验学校",
        "district": "南山区",
        "stage": "小学",
        "subject": "语文",
        "is_establishment": True,
        "salary_min": 15000,
        "salary_max": 23000,
        "recruiter_email": "hr@example.com",
        "description": "班主任经验优先。",
        "deadline": None,
    }
    data.update(overrides)
    return RawJob(**data)


def test_content_hash_is_stable_and_sensitive_to_content():
    raw = make_raw_job()
    assert content_hash(raw) == content_hash(raw)
    assert content_hash(raw) != content_hash(replace(raw, description="普通话二甲优先。"))


def test_upsert_jobs_deduplicates_and_updates(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'teacher_jobs.db'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    with Session() as db:
        first = make_raw_job()
        assert upsert_jobs(db, [first]) == {"new": 1, "updated": 0}

        second = make_raw_job(
            description="班主任经验优先，能带校队。",
            salary_min=18000,
        )
        assert upsert_jobs(db, [second]) == {"new": 0, "updated": 1}

        jobs = db.scalars(select(Job)).all()
        assert len(jobs) == 1
        job = jobs[0]
        assert job.description == second.description
        assert job.salary_min == 18000
        assert job.content_hash == content_hash(second)
