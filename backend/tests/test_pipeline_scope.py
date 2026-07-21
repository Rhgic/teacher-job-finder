"""run_pipeline 的 user_id 作用域测试。

Web 体验用户的"运行匹配"依赖这个语义：只跑自己的规则、
不碰其他用户，也不因传了 user_id 而改变全量行为。
"""
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from models import Base, Job, MatchResult, SubRule, User
from services.pipeline import run_pipeline


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


def make_user_with_rule(db, openid: str) -> User:
    user = User(openid=openid)
    db.add(user)
    db.flush()
    db.add(SubRule(user_id=user.id, name=f"{openid} 的规则", subjects=["语文"]))
    db.flush()
    return user


def test_user_scope_only_runs_own_rules(db):
    """给定 user_id 时，只为该用户产出匹配。"""
    a = make_user_with_rule(db, "guest_a")
    make_user_with_rule(db, "guest_b")
    db.add(Job(school_name="南山实验学校", subject="语文", stage="小学"))
    db.flush()

    stats = run_pipeline(db, user_id=a.id)

    assert stats["rules"] == 1
    assert stats["new_matches"] == 1
    owners = {m.user_id for m in db.scalars(select(MatchResult)).all()}
    assert owners == {a.id}


def test_no_user_scope_runs_all_rules(db):
    """不给 user_id 时行为不变：全量规则都跑。"""
    make_user_with_rule(db, "guest_a")
    make_user_with_rule(db, "guest_b")
    db.add(Job(school_name="南山实验学校", subject="语文", stage="小学"))
    db.flush()

    stats = run_pipeline(db)

    assert stats["rules"] == 2
    assert stats["new_matches"] == 2


def test_unknown_user_matches_nothing(db):
    """体验身份还没建规则时，跑匹配应安静返回零，而不是报错。"""
    make_user_with_rule(db, "guest_a")
    db.add(Job(school_name="南山实验学校", subject="语文", stage="小学"))
    db.flush()

    stats = run_pipeline(db, user_id="no-such-user")

    assert stats == {"rules": 0, "jobs": 1, "new_matches": 0}
