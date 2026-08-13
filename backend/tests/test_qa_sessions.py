"""公告问答会话：持久化、出处、岗位上下文、用户隔离。

问答做成持久化而不是纯前端状态，是因为用户换台设备或只是刷新页面，
问过什么、AI 依据哪条公告答的，都该还在。这里守住那条链路。
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from config import settings
from database import get_db
from main import app
from models import Base, Job
from services import rag_index


@pytest.fixture
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'qa.db'}", future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


@pytest.fixture
def client(session_factory):
    def override():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def indexed_job(session_factory):
    """一条真实岗位并建好检索索引，让问答有东西可命中。"""
    db = session_factory()
    try:
        job = Job(
            school_name="南山第二实验学校", subject="语文", subjects="|语文|",
            stage="小学", district="南山区",
            description="招聘小学语文教师。报名需提交报名表、身份证、教师资格证复印件。面试比例1:3。",
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        rag_index.reindex(db)
        return job.id
    finally:
        db.close()


@pytest.fixture(autouse=True)
def stub_llm(monkeypatch):
    """用占位模型，测的是会话链路本身，不是模型输出质量。"""
    monkeypatch.setattr(settings, "LLM_STUB_MODE", True)


def _auth(client, email="qa@example.com"):
    r = client.post("/auth/register", json={"email": email, "password": "pw12345678"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_first_question_creates_session_with_sources(client, indexed_job):
    h = _auth(client)
    r = client.post("/qa/ask", json={"question": "报名需要哪些材料？"}, headers=h).json()

    assert r["session_id"]
    assert r["found"] is True
    assert r["sources"], "回答必须带出处，否则无从核对"
    # 出处要带 job_id，前端才能做成可点开的链接
    assert r["sources"][0]["job_id"] == indexed_job
    assert r["sources"][0]["title"]


def test_follow_up_stays_in_same_session(client, indexed_job):
    h = _auth(client)
    sid = client.post("/qa/ask", json={"question": "报名材料？"}, headers=h).json()["session_id"]

    r2 = client.post(f"/qa/sessions/{sid}/ask",
                     json={"question": "面试比例呢？"}, headers=h).json()
    assert r2["session_id"] == sid

    detail = client.get(f"/qa/sessions/{sid}", headers=h).json()
    assert [m["role"] for m in detail["messages"]] == [
        "user", "assistant", "user", "assistant",
    ]


def test_history_survives_relogin(client, indexed_job):
    """重新登录后还能看到自己的历史会话——这是持久化的意义。"""
    h = _auth(client)
    client.post("/qa/ask", json={"question": "报名材料？"}, headers=h)

    again = client.post("/auth/login",
                        json={"email": "qa@example.com", "password": "pw12345678"}).json()
    h2 = {"Authorization": f"Bearer {again['token']}"}

    assert len(client.get("/qa/sessions", headers=h2).json()) == 1


def test_job_context_is_bound_to_session(client, indexed_job):
    """从岗位详情进来的会话记住是哪个岗位。"""
    h = _auth(client)
    r = client.post("/qa/ask",
                    json={"question": "有编制吗？", "job_id": indexed_job}, headers=h).json()

    detail = client.get(f"/qa/sessions/{r['session_id']}", headers=h).json()
    assert detail["job_id"] == indexed_job


def test_unknown_job_id_is_rejected(client, indexed_job):
    h = _auth(client)
    r = client.post("/qa/ask",
                    json={"question": "在吗", "job_id": "no-such-job"}, headers=h)
    assert r.status_code == 404


def test_sessions_are_isolated_between_users(client, indexed_job):
    """B 既看不到 A 的列表，也不能拿 id 直接取 A 的会话。"""
    ha = _auth(client, "a@example.com")
    sid = client.post("/qa/ask", json={"question": "材料？"}, headers=ha).json()["session_id"]

    hb = _auth(client, "b@example.com")
    assert client.get("/qa/sessions", headers=hb).json() == []
    # 404 而不是 403：403 等于告诉对方"这个 id 存在，只是不属于你"
    assert client.get(f"/qa/sessions/{sid}", headers=hb).status_code == 404
    assert client.delete(f"/qa/sessions/{sid}", headers=hb).status_code == 404


def test_guest_cannot_use_qa(client, indexed_job):
    """访客不能保存任何数据，问答会话也是数据。"""
    token = client.post("/auth/guest").json()["token"]
    r = client.post("/qa/ask", json={"question": "材料？"},
                    headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


def test_missing_key_returns_guidance_not_a_fake_answer(client, indexed_job, monkeypatch):
    """没配 Key 时给可识别的引导码，绝不返回编造的答案。"""
    monkeypatch.setattr(settings, "LLM_STUB_MODE", False)
    h = _auth(client)

    r = client.post("/qa/ask", json={"question": "材料？"}, headers=h)

    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "model_key_missing"
    # 也不该因此留下半截会话
    assert client.get("/qa/sessions", headers=h).json() == []


def test_empty_and_overlong_questions_rejected(client, indexed_job):
    h = _auth(client)
    assert client.post("/qa/ask", json={"question": "   "}, headers=h).status_code == 422
    assert client.post("/qa/ask", json={"question": "啊" * 501}, headers=h).status_code == 422


def test_delete_session_removes_its_messages(client, indexed_job):
    h = _auth(client)
    sid = client.post("/qa/ask", json={"question": "材料？"}, headers=h).json()["session_id"]

    assert client.delete(f"/qa/sessions/{sid}", headers=h).status_code == 200
    assert client.get(f"/qa/sessions/{sid}", headers=h).status_code == 404
