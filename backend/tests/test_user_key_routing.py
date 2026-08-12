"""每用户 Key 的路由与隔离。

这一层要守住三件事，任何一条破了都是真实的钱或隐私问题：
1. 没配 Key 时不发起模型调用，也不假装有答案，而是给出可识别的引导码。
2. 用谁的 Key 由"任务归属谁"决定，不会串用别人的。
3. Key 不出现在任务载荷里——载荷会进 Redis，那是另一个进程能读到的地方。
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from config import settings
from database import get_db
from main import app
from models import Base, User, UserModelConfig
from services import crypto, llm_credentials
from services.auth import make_token
from services.llm_credentials import LLMCredential, NoUserKey, UserKeyUnreadable


@pytest.fixture
def session_factory(tmp_path):
    """独立的临时库。不能用生产 SessionLocal——它指向开发用的
    teacher_jobs.db，schema 可能是旧的，且会把测试数据写进真实文件。"""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'keys.db'}", future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


@pytest.fixture
def db(session_factory):
    s = session_factory()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def client(session_factory):
    def override_get_db():
        s = session_factory()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def real_mode(monkeypatch):
    """关掉 stub，让凭据解析走真实分支。"""
    monkeypatch.setattr(settings, "LLM_STUB_MODE", False)


def _mk_user(db, email: str) -> User:
    u = User(email=email, password_hash="x", is_guest=False)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _give_key(db, user: User, plain: str, model: str = "deepseek-chat") -> None:
    db.add(UserModelConfig(
        user_id=user.id,
        encrypted_key=crypto.encrypt(plain),
        key_last4=plain[-4:],
        key_fingerprint=crypto.fingerprint(plain),
        model=model,
    ))
    db.commit()


def test_resolve_returns_that_users_own_key(db, real_mode):
    """A 的调用必须拿到 A 的 Key 和 A 选的模型，不能串到 B。"""
    a = _mk_user(db, "keya@example.com")
    b = _mk_user(db, "keyb@example.com")
    _give_key(db, a, "sk-" + "a" * 28 + "AAAA", model="deepseek-chat")
    _give_key(db, b, "sk-" + "b" * 28 + "BBBB", model="deepseek-reasoner")

    cred_a = llm_credentials.resolve_for_user(db, a.id)
    cred_b = llm_credentials.resolve_for_user(db, b.id)

    assert cred_a.api_key.endswith("AAAA")
    assert cred_a.model == "deepseek-chat"
    assert cred_b.api_key.endswith("BBBB")
    assert cred_b.model == "deepseek-reasoner"


def test_resolve_raises_when_user_has_no_key(db, real_mode):
    """没配就抛 NoUserKey，而不是退回服务器全局 Key。"""
    u = _mk_user(db, "nokey@example.com")
    with pytest.raises(NoUserKey):
        llm_credentials.resolve_for_user(db, u.id)


def test_resolve_raises_unreadable_when_ciphertext_broken(db, real_mode):
    """密文坏掉要与"没配"区分开：引导语不同。"""
    u = _mk_user(db, "broken@example.com")
    db.add(UserModelConfig(
        user_id=u.id, encrypted_key="not-a-valid-fernet-token",
        key_last4="xxxx", key_fingerprint="f", model="deepseek-chat",
    ))
    db.commit()
    with pytest.raises(UserKeyUnreadable):
        llm_credentials.resolve_for_user(db, u.id)


def test_credential_repr_never_shows_the_key():
    """一句 print(cred) 或异常回溯里的局部变量展示就能把 Key 写进日志。"""
    cred = LLMCredential(api_key="sk-super-secret-value", model="deepseek-chat")
    assert "super-secret" not in repr(cred)
    assert "***" in repr(cred)


def test_call_deepseek_requires_explicit_credential():
    """不给 cred 必须 TypeError。

    这是本次改造的安全支点：漏改的调用点会在这里当场炸掉，
    而不是静默地继续用服务器全局 Key（那样账单照出、结果照常，
    没有任何迹象表明这条路径没改到）。
    """
    from services import llm_match

    with pytest.raises(TypeError):
        llm_match._call_deepseek("sys", "user")


def test_stub_credential_never_reaches_network():
    """stub 凭据若走到真实调用就是逻辑错误，要显式炸而不是发请求。"""
    from services import llm_match

    with pytest.raises(RuntimeError, match="stub"):
        llm_match._call_deepseek("sys", "user",
                                 cred=llm_credentials.stub_credential())


def test_ask_without_key_returns_guidance_code(client, db, real_mode):
    """没配 Key 时问答返回 409 + 可识别 code，前端据此引导，不显示伪造答案。"""
    uid = _mk_user(db, "asknokey@example.com").id

    resp = client.post("/rag/ask", json={"question": "报名要什么材料"},
                       headers={"Authorization": f"Bearer {make_token(uid)}"})

    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "model_key_missing"


def test_enqueued_task_payload_carries_no_key_material(db, real_mode):
    """任务载荷只能有 user_id / task_id。

    载荷会进 Redis——那是 worker 进程、运维、甚至备份都能读到的地方。
    明文 Key 固然不能进，密文同样不行：密文加上环境里的主密钥就是明文，
    而 worker 本来就有主密钥。载荷里放密文没有任何收益，只扩大暴露面。
    """
    import asyncio
    import importlib.util

    # conftest 的 autouse 夹具把 services.tasks.enqueue_refresh 短路成了
    # "队列不可用"，直接调用它测不到真实载荷。这里单独加载一份模块实例，
    # 拿到未被打桩的实现，同时不影响其它用例看到的那份。
    spec = importlib.util.find_spec("services.tasks")
    tasks = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tasks)

    captured = {}

    class FakePool:
        async def enqueue_job(self, name, *args, **kw):
            captured["name"] = name
            captured["args"] = args
            captured["kw"] = kw

            class Job:
                job_id = kw.get("_job_id", "j")
            return Job()

    async def fake_pool():
        return FakePool()

    u = _mk_user(db, "queue@example.com")
    secret = "sk-" + "q" * 28 + "QQQQ"
    _give_key(db, u, secret)
    uid = u.id
    cipher = db.scalar(
        select(UserModelConfig.encrypted_key)
        .where(UserModelConfig.user_id == uid)
    )

    tasks._get_pool = fake_pool
    asyncio.run(tasks.enqueue_refresh(uid))

    blob = repr(captured)
    assert uid in blob, "载荷里应当有 user_id，worker 靠它去查 Key"
    assert secret not in blob, "明文 Key 进了任务载荷"
    assert cipher not in blob, "密文 Key 进了任务载荷"
