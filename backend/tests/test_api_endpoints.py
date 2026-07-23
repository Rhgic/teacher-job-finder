"""接口级测试：穿过完整栈跑真实 HTTP 请求。

与其余单测的分工：那些测纯函数的内部逻辑，这里测的是
路由匹配、依赖注入、鉴权、Pydantic 序列化、异常处理器——
这几层此前完全没有测试覆盖，改坏了只能靠手工点页面才发现。

数据库用临时 SQLite 并覆盖 get_db 依赖；
不使用 TestClient 的上下文管理器，避免触发 lifespan 里的 init_db
去建真实库的表。
"""
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import get_db
from main import app
from models import Base, Job, Resume, SubRule, User
from services.auth import make_token


@pytest.fixture
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'api.db'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


@pytest.fixture
def client(session_factory):
    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def seeded(session_factory):
    """一个用户 + 一份默认简历 + 三个岗位（在招/已截止/无邮箱）。"""
    with session_factory() as db:
        user = User(openid="guest_apitest", nickname="接口测试用户")
        db.add(user)
        db.flush()
        db.add(Resume(user_id=user.id, file_name="简历.pdf", file_url="", is_default=True))
        open_job = Job(school_name="南山实验学校", stage="小学", subject="语文",
                       district="南山区", is_establishment=True,
                       recruiter_email="hr@example.edu.cn",
                       deadline=date.today() + timedelta(days=30),
                       description="招聘小学语文教师若干名。")
        expired_job = Job(school_name="已截止中学", stage="初中", subject="数学",
                          recruiter_email="hr2@example.edu.cn",
                          deadline=date.today() - timedelta(days=1))
        no_email_job = Job(school_name="无邮箱小学", stage="小学", subject="英语",
                           deadline=date.today() + timedelta(days=10))
        db.add_all([open_job, expired_job, no_email_job])
        db.commit()
        return {
            "user_id": user.id,
            "token": make_token(user.id),
            "open_job": open_job.id,
            "expired_job": expired_job.id,
            "no_email_job": no_email_job.id,
        }


def auth(token):
    return {"Authorization": f"Bearer {token}"}


# ---------------- 公开读路径 ----------------

def test_health_needs_no_auth(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_jobs_list_serializes_expected_fields(client, seeded):
    resp = client.get("/jobs")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) >= 1
    job = body[0]
    # JobOut 没有 title 字段——标题由前端 buildJobTitle 拼；
    # 这里锁住契约，避免有人"顺手"加字段又不同步前端。
    assert "title" not in job
    assert {"id", "school_name", "deadline"} <= set(job)


def test_jobs_list_hides_expired_by_default(client, seeded):
    default_ids = {j["id"] for j in client.get("/jobs").json()}
    all_ids = {j["id"] for j in client.get("/jobs?include_expired=true").json()}
    assert seeded["expired_job"] not in default_ids
    assert seeded["expired_job"] in all_ids


def test_job_detail_includes_description(client, seeded):
    resp = client.get(f"/jobs/{seeded['open_job']}")
    assert resp.status_code == 200
    assert "招聘小学语文教师" in resp.json()["description"]


def test_jobs_pagination_pages_are_disjoint_and_complete(client, seeded):
    """岗位页靠翻页把在招岗位取全，所以分页必须既不重复也不漏。

    size 上限是 100，前端翻到某页返回不满一页才停——这个"不满即结束"的
    约定一旦破了（比如某页因排序不稳定少给一条），页面会安静地少显示岗位，
    而搜索搜不到和岗位不存在，在用户看来是一回事。
    """
    p1 = client.get("/jobs?size=1&page=1").json()
    p2 = client.get("/jobs?size=1&page=2").json()
    all_ids = {j["id"] for j in client.get("/jobs?size=100&page=1").json()}

    assert len(p1) == 1 and len(p2) == 1
    assert p1[0]["id"] != p2[0]["id"]           # 不重复
    assert {p1[0]["id"], p2[0]["id"]} <= all_ids  # 不越界
    # 翻过尾页返回空，前端据此停止
    assert client.get("/jobs?size=100&page=99").json() == []


def test_job_detail_404_for_unknown_id(client, seeded):
    resp = client.get("/jobs/no-such-job")
    assert resp.status_code == 404


def test_taxonomy_is_not_trimmed_by_data(client, seeded):
    """订阅规则的可选项来自标准表，不能被库中现有数据裁剪。"""
    body = client.get("/taxonomy").json()
    assert "体育" in body["subjects"]      # 库里三个岗位都没有体育
    assert "深汕特别合作区" in body["districts"]


# ---------------- 鉴权 ----------------

def test_guest_login_issues_usable_token(client):
    resp = client.post("/auth/guest")
    assert resp.status_code == 200
    token = resp.json()["token"]
    assert client.get("/recommendations", headers=auth(token)).status_code == 200


def test_forged_token_is_rejected(client, seeded):
    """签名被篡改必须拒绝——会话令牌是 HMAC 签的，不能只看格式。"""
    forged = seeded["token"][:-1] + ("0" if seeded["token"][-1] != "0" else "1")
    resp = client.get("/recommendations", headers=auth(forged))
    assert resp.status_code == 401


def test_malformed_token_is_rejected(client):
    resp = client.get("/recommendations", headers=auth("not-a-valid-token"))
    assert resp.status_code == 401


def test_protected_route_401_without_token_in_production(client, seeded, monkeypatch):
    """AUTH_DEV_MODE=0 时无令牌必须 401。

    生产必须关掉 dev 回退，否则任何人都能读到 demo 用户的数据。
    """
    from config import settings

    monkeypatch.setattr(settings, "AUTH_DEV_MODE", False)
    assert client.get("/recommendations").status_code == 401
    assert client.get("/applications").status_code == 401
    # 岗位是公开数据，不该被鉴权挡住
    assert client.get("/jobs").status_code == 200


# ---------------- 投递主链路 ----------------

def test_apply_flow_persists_choices(client, seeded):
    """选定的简历与自定义邮件主题必须如实落库，不能被默认值覆盖。"""
    with_resume = client.get("/resumes", headers=auth(seeded["token"])).json()
    resume_id = with_resume[0]["id"]

    resp = client.post("/applications", headers=auth(seeded["token"]), json={
        "job_id": seeded["open_job"],
        "resume_id": resume_id,
        "email_subject": "应聘南山实验学校语文教师",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["recipient_email"] == "hr@example.edu.cn"

    listed = client.get("/applications", headers=auth(seeded["token"])).json()
    assert len(listed) == 1
    # 枚举值是小写（ApplicationStatus.SENT = "sent"），接口原样返回；
    # 前端用 toUpperCase() 兜住大小写，这里按接口真实契约断言。
    assert listed[0]["status"] == "sent"   # MAILER_DRY_RUN=1 下视为发送成功


def test_apply_to_expired_job_is_blocked(client, seeded):
    """已截止岗位的投递防线——穿过完整栈验证，而非只测 _send_one。"""
    resp = client.post("/applications", headers=auth(seeded["token"]),
                       json={"job_id": seeded["expired_job"]})
    assert resp.status_code == 400
    assert "已过截止日期" in resp.json()["detail"]
    assert client.get("/applications", headers=auth(seeded["token"])).json() == []


def test_apply_without_recruiter_email_is_blocked(client, seeded):
    resp = client.post("/applications", headers=auth(seeded["token"]),
                       json={"job_id": seeded["no_email_job"]})
    assert resp.status_code == 400
    assert "邮箱" in resp.json()["detail"]


def test_apply_to_unknown_job_404(client, seeded):
    resp = client.post("/applications", headers=auth(seeded["token"]),
                       json={"job_id": "no-such-job"})
    assert resp.status_code == 404


# ---------------- 订阅规则 CRUD ----------------

def test_rules_crud_roundtrip(client, seeded):
    token = seeded["token"]
    created = client.post("/rules", headers=auth(token), json={
        "name": "南山小学语文", "stages": ["小学"], "subjects": ["语文"],
        "districts": ["南山区"], "need_establishment": True,
    })
    assert created.status_code == 200
    rule_id = created.json()["id"]

    assert len(client.get("/rules", headers=auth(token)).json()) == 1

    updated = client.put(f"/rules/{rule_id}", headers=auth(token), json={
        "name": "改名后", "subjects": ["数学"], "is_active": False,
    })
    assert updated.status_code == 200
    assert updated.json()["name"] == "改名后"
    assert updated.json()["is_active"] is False

    assert client.delete(f"/rules/{rule_id}", headers=auth(token)).status_code == 200
    assert client.get("/rules", headers=auth(token)).json() == []


def test_rules_are_scoped_to_owner(client, seeded, session_factory):
    """一个用户不该看见或改动别人的规则。"""
    with session_factory() as db:
        other = User(openid="guest_other")
        db.add(other)
        db.flush()
        db.add(SubRule(user_id=other.id, name="别人的规则"))
        db.commit()
        other_token = make_token(other.id)

    mine = client.get("/rules", headers=auth(seeded["token"])).json()
    assert mine == []
    theirs = client.get("/rules", headers=auth(other_token)).json()
    assert len(theirs) == 1


def test_recommendations_expose_match_breakdown(client, seeded, session_factory):
    """/recommendations 必须把命中点与差距带给前端。

    存了不返回，等于换个地方丢掉——推荐页依然只能显示一个光秃秃的分数。
    """
    from models import MatchResult, SubRule

    with session_factory() as db:
        rule = SubRule(user_id=seeded["user_id"], name="规则")
        db.add(rule)
        db.flush()
        db.add(MatchResult(
            rule_id=rule.id, job_id=seeded["open_job"], user_id=seeded["user_id"],
            rule_passed=True, llm_score=82,
            match_reason="学科与区域均匹配",
            matched_points=["学科匹配：语文", "区域符合：南山区"],
            gaps=["JD 要求班主任经验，简历未体现"],
        ))
        db.commit()

    body = client.get("/recommendations", headers=auth(seeded["token"])).json()
    assert len(body) == 1
    assert body[0]["matched_points"] == ["学科匹配：语文", "区域符合：南山区"]
    assert body[0]["gaps"] == ["JD 要求班主任经验，简历未体现"]


# ---------------- 异步匹配任务 ----------------

def test_refresh_falls_back_to_sync_when_queue_unavailable(client, seeded):
    """队列不可用时必须当场跑完并返回结果，而不是报错。

    这是"降级优先于保护"在异步化之后的延续：异步是体验优化，
    Redis 挂掉时用户可以等得久一点，但不能连匹配都跑不了。
    conftest 已把入队短路成不可用，这里跑的就是兜底路径。
    """
    resp = client.post("/matches/refresh", headers=auth(seeded["token"]))
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "sync"
    assert body["status"] == "done"
    assert "new_matches" in body       # 同步兜底必须直接给出结果
    assert "task_id" not in body       # 没有队列就没有可轮询的任务


def test_refresh_status_404_for_unknown_task(client, seeded):
    resp = client.get("/matches/refresh/no-such-task", headers=auth(seeded["token"]))
    assert resp.status_code == 404


def test_refresh_status_hides_other_users_task(client, seeded, monkeypatch):
    """task_id 是可猜的字符串，不校验归属就等于凭 ID 能读别人的匹配结果。

    且必须与"任务不存在"返回同样的 404——区分开来，这个接口就成了
    探测他人任务 ID 是否有效的工具。
    """
    from services import tasks

    monkeypatch.setattr(tasks, "read_state", lambda _tid: {
        "status": "done", "user_id": "someone-else", "new_matches": 7,
    })
    resp = client.get("/matches/refresh/borrowed-id", headers=auth(seeded["token"]))
    assert resp.status_code == 404
    assert "7" not in resp.text


def test_refresh_status_returns_own_task(client, seeded, monkeypatch):
    from services import tasks

    monkeypatch.setattr(tasks, "read_state", lambda _tid: {
        "status": "running", "user_id": seeded["user_id"], "done": 3, "total": 10,
    })
    body = client.get("/matches/refresh/mine", headers=auth(seeded["token"])).json()
    assert body["task_id"] == "mine"
    assert (body["done"], body["total"]) == (3, 10)


# ---------------- 静态前端挂载 ----------------

def test_root_redirects_to_web(client):
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 307
    assert resp.headers["location"] == "/web/"


@pytest.mark.parametrize("page", [
    "", "recommend.html", "ask.html", "applications.html",
    "me.html", "job.html", "apply.html", "rules.html",
])
def test_web_pages_are_served(client, page):
    """八个页面都要能被后端托管——漏挂一个就是线上 404。"""
    assert client.get(f"/web/{page}").status_code == 200


# ---------------- 可观测性 ----------------

def test_every_response_carries_request_id(client):
    """报障时用户提供的 ID 要能在日志里捞到堆栈，这个头不能丢。"""
    resp = client.get("/health")
    assert resp.headers.get("X-Request-ID")


def test_metrics_aggregates_by_route_template(client, seeded):
    """按路由模板聚合，不能按真实路径——否则每个岗位 ID 一条时间序列。"""
    client.get(f"/jobs/{seeded['open_job']}")
    body = client.get("/metrics").text
    assert 'route="/jobs/{job_id}"' in body
    assert seeded["open_job"] not in body
