"""投递防线测试。

覆盖 routers/applications.py 的 _send_one —— 单条投递和批量确认都走这个函数，
所以守住它就守住了两条入口。重点是"岗位已过截止日期不得投递"这条业务规则：
它此前只在需要真实后端的冒烟脚本里被验证，而种子数据里没有已截止岗位，
那条断言实际一直被跳过。
"""
from datetime import date, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from models import Application, Base, Job, User
from routers.applications import _send_one
from schemas import ApplicationCreate


@pytest.fixture
def db(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'teacher_jobs.db'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    with Session() as session:
        yield session


@pytest.fixture
def user(db):
    u = User(openid="test-openid")
    db.add(u)
    db.flush()
    return u


def make_job(db, **overrides):
    data = {
        "school_name": "南山实验学校",
        "recruiter_email": "hr@example.edu.cn",
        "deadline": None,
    }
    data.update(overrides)
    job = Job(**data)
    db.add(job)
    db.flush()
    return job


def body_for(job):
    return ApplicationCreate(job_id=job.id)


def test_expired_job_is_rejected(db, user):
    """已过截止日期的岗位必须拒绝，且不留下任何投递记录。"""
    job = make_job(db, deadline=date.today() - timedelta(days=1))

    with pytest.raises(HTTPException) as exc:
        _send_one(db, user, job, body_for(job))

    assert exc.value.status_code == 400
    assert "已过截止日期" in exc.value.detail
    # 防线的意义在于"拦住"，所以要确认没有半条记录漏进库。
    assert db.scalars(select(Application)).all() == []


def test_deadline_today_is_still_allowed(db, user):
    """边界：截止日期就是今天仍可投递（规则是 deadline < today 才算过期）。"""
    job = make_job(db, deadline=date.today())

    app = _send_one(db, user, job, body_for(job))

    assert app.job_id == job.id


def test_job_without_deadline_is_allowed(db, user):
    """没有截止日期的岗位不受该防线影响。"""
    job = make_job(db, deadline=None)

    app = _send_one(db, user, job, body_for(job))

    assert app.job_id == job.id


def test_job_without_recruiter_email_is_rejected(db, user):
    """缺投递邮箱同样拦下——否则会生成一条永远发不出去的记录。"""
    job = make_job(db, recruiter_email=None)

    with pytest.raises(HTTPException) as exc:
        _send_one(db, user, job, body_for(job))

    assert exc.value.status_code == 400
    assert "缺少招聘方邮箱" in exc.value.detail
    assert db.scalars(select(Application)).all() == []
