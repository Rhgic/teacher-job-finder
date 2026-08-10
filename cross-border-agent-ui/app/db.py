"""SQLAlchemy 引擎与会话。"""

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

settings = get_settings()

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,  # 容器重启后连接会失效，预检省掉一次必然失败的查询
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def get_db() -> Iterator[Session]:
    """FastAPI 依赖：每请求一个会话，结束即关闭。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
