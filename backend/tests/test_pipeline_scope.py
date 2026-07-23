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


def test_progress_reports_total_before_first_llm_call(db):
    """进度必须先报总数再开跑——否则前端只能显示"已评 N 个"这种没有分母的数。

    分母还有一层意义：它等于这次要花掉的模型调用次数，
    是在开跑前就该知道的成本，而不是跑完才知道。
    """
    make_user_with_rule(db, "guest_a")
    db.add_all([
        Job(school_name=f"学校{i}", subject="语文", stage="小学") for i in range(3)
    ])
    db.add(Job(school_name="不匹配的", subject="数学", stage="小学"))  # 规则层就被筛掉
    db.flush()

    seen: list[tuple[int, int]] = []
    stats = run_pipeline(db, user_id=None, on_progress=lambda d, t: seen.append((d, t)))

    assert seen[0] == (0, 3)                     # 开跑前先报分母，且不含被规则筛掉的
    assert seen == [(0, 3), (1, 3), (2, 3), (3, 3)]
    assert stats["new_matches"] == 3


def test_match_breakdown_is_persisted(db):
    """命中点与差距必须落库。

    模型每次都在输出这两项、token 也付了，之前没有列可存就被丢掉，
    推荐页只剩一个无法解释的分数。这条测试守的就是"别再扔了"。
    """
    make_user_with_rule(db, "guest_a")
    db.add(Job(school_name="南山实验学校", subject="语文", stage="小学"))
    db.flush()

    run_pipeline(db)

    match = db.scalars(select(MatchResult)).one()
    assert match.matched_points  # stub 也会给出命中点
    assert isinstance(match.matched_points, list)
    # gaps 为空数组时存 NULL 而不是 []，前端两种都按"无差距"渲染
    assert match.gaps is None or isinstance(match.gaps, list)


def test_progress_is_optional(db):
    """不传回调时行为不变——定时任务与管理端调用不需要进度。"""
    make_user_with_rule(db, "guest_a")
    db.add(Job(school_name="南山实验学校", subject="语文", stage="小学"))
    db.flush()

    assert run_pipeline(db)["new_matches"] == 1


def test_unknown_user_matches_nothing(db):
    """体验身份还没建规则时，跑匹配应安静返回零，而不是报错。"""
    make_user_with_rule(db, "guest_a")
    db.add(Job(school_name="南山实验学校", subject="语文", stage="小学"))
    db.flush()

    stats = run_pipeline(db, user_id="no-such-user")

    assert stats == {"rules": 0, "jobs": 1, "new_matches": 0}
