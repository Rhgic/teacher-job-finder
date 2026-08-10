"""测试只使用 PostgreSQL，绝不悄悄换成内存数据库。"""

import os

# conftest 在 app.* 导入前执行，确保应用引擎指向独立测试库。
os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg://cbagent:cbagent@localhost:5433/cbagent_test"
)
# 至少 32 字节，与 Settings.MIN_JWT_SECRET_BYTES 一致；
# 短密钥会让 PyJWT 发 InsecureKeyLengthWarning，测试里也不该出现。
os.environ.setdefault("JWT_SECRET", "t" * 64)
os.environ.setdefault("SEED_PASSWORD", "demo1234")

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings

get_settings.cache_clear()
from app.db import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402
from app.seed import main as seed_main  # noqa: E402


def _psycopg_url(database: str) -> str:
    url = get_settings().database_url.replace("postgresql+psycopg://", "postgresql://")
    return url.rsplit("/", 1)[0] + "/" + database


@pytest.fixture(scope="session", autouse=True)
def test_database():
    """创建 cbagent_test；连接不可用时明确失败，提示先启动 PostgreSQL。"""
    try:
        with psycopg.connect(_psycopg_url("postgres"), autocommit=True) as conn:
            exists = conn.execute(
                "SELECT 1 FROM pg_database WHERE datname = 'cbagent_test'"
            ).fetchone()
            if not exists:
                conn.execute("CREATE DATABASE cbagent_test")
    except psycopg.OperationalError as exc:
        pytest.fail(
            f"PostgreSQL 测试库不可用，请先执行 docker compose up -d db：{type(exc).__name__}"
        )

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    seed_main()
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def login(client: TestClient, username: str = "agent") -> dict[str, str]:
    response = client.post("/api/auth/login", json={"username": username, "password": "demo1234"})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture()
def agent_headers(client):
    return login(client, "agent")


@pytest.fixture()
def admin_headers(client):
    return login(client, "admin")
