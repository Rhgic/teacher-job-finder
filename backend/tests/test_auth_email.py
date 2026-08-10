"""邮箱账户与用户模型配置的接口测试。

这些测试不使用 TestClient 的上下文管理器，因此不会触发生产 lifespan；
数据库改为临时 SQLite，DeepSeek 校验也一律 stub，确保测试不会碰网络或真实 Key。
"""
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from database import get_db
from main import app
from models import Base, UserModelConfig
from services import deepseek_verify


TEST_KEY = "sk-this-is-a-test-only-key-1234567890"


@pytest.fixture
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'accounts.db'}",
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


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def register(client: TestClient, email: str = "teacher@example.com") -> dict:
    response = client.post("/auth/register", json={
        "email": email,
        "password": "a-safe-password",
        "nickname": "李老师",
    })
    assert response.status_code == 200, response.text
    return response.json()


def test_register_login_and_rehash_safe_password(client):
    created = register(client)
    assert created["email"] == "teacher@example.com"
    assert created["is_guest"] is False
    assert "password" not in created

    duplicate = client.post("/auth/register", json={
        "email": "TEACHER@example.com", "password": "another-safe-password",
    })
    assert duplicate.status_code == 409

    wrong = client.post("/auth/login", json={
        "email": "teacher@example.com", "password": "wrong-password",
    })
    assert wrong.status_code == 401
    assert wrong.json()["detail"] == "邮箱或密码不正确"

    logged_in = client.post("/auth/login", json={
        "email": "teacher@example.com", "password": "a-safe-password",
    })
    assert logged_in.status_code == 200
    assert logged_in.json()["token"]


def test_guest_cannot_write_personal_data(client):
    guest = client.post("/auth/guest").json()
    response = client.put("/profile", headers=auth(guest["token"]), json={
        "real_name": "体验用户",
    })
    assert response.status_code == 401
    assert "不能保存数据" in response.json()["detail"]


def test_key_is_verified_encrypted_masked_and_scoped(client, session_factory, monkeypatch):
    monkeypatch.setattr(deepseek_verify, "verify_key", lambda _key, _model: (True, ""))
    alice = register(client, "alice@example.com")
    bob = register(client, "bob@example.com")

    saved = client.put("/model-config", headers=auth(alice["token"]), json={
        "api_key": TEST_KEY,
        "model": "deepseek-chat",
    })
    assert saved.status_code == 200, saved.text
    payload = saved.json()
    assert payload["configured"] is True
    assert payload["masked_key"] == f"sk-****{TEST_KEY[-4:]}"
    assert TEST_KEY not in saved.text
    assert "encrypted_key" not in payload

    with session_factory() as db:
        config = db.scalar(select(UserModelConfig))
        assert config is not None
        assert config.encrypted_key != TEST_KEY
        assert TEST_KEY not in config.encrypted_key
        assert config.key_last4 == TEST_KEY[-4:]

    # 另一用户没有读取 Alice 配置的路径，自己的 GET 只会得到未配置状态。
    other = client.get("/model-config", headers=auth(bob["token"]))
    assert other.status_code == 200
    assert other.json()["configured"] is False

    relogin = client.post("/auth/login", json={
        "email": "alice@example.com", "password": "a-safe-password",
    }).json()
    restored = client.get("/model-config", headers=auth(relogin["token"]))
    assert restored.json()["masked_key"] == f"sk-****{TEST_KEY[-4:]}"


def test_invalid_key_is_not_persisted(client, session_factory, monkeypatch):
    monkeypatch.setattr(
        deepseek_verify, "verify_key", lambda _key, _model: (False, "invalid_key"),
    )
    user = register(client)
    rejected = client.put("/model-config", headers=auth(user["token"]), json={
        "api_key": TEST_KEY,
        "model": "deepseek-reasoner",
    })
    assert rejected.status_code == 400
    assert TEST_KEY not in rejected.text

    with session_factory() as db:
        assert db.scalar(select(UserModelConfig)) is None
