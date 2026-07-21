"""
数据库连接与会话管理。

生产默认 MySQL 8（utf8mb4）；本地开发和单元测试可继续用 SQLite（零配置）。
切换只改 DATABASE_URL，业务代码不动：
  MySQL:      mysql+pymysql://user:pwd@host:3306/teacher_jobs?charset=utf8mb4
  SQLite:     sqlite:///./teacher_jobs.db
  PostgreSQL: postgresql+psycopg://user:pwd@host:5432/teacher_jobs
"""
import os

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session

from models import Base

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./teacher_jobs.db")

IS_SQLITE = DATABASE_URL.startswith("sqlite")
IS_MYSQL = DATABASE_URL.startswith("mysql")


def _engine_kwargs() -> dict:
    """按数据库类型给出连接参数。

    MySQL 的两个必配项：
    - pool_pre_ping：MySQL 会断开空闲超过 wait_timeout（默认 8 小时）的连接，
      连接池里的死连接不检测就会抛 "MySQL server has gone away"。
    - pool_recycle：早于服务端 wait_timeout 主动回收，从源头减少上面那种死连接。
    """
    if IS_SQLITE:
        # SQLite 是本地文件，没有网络连接池语义；只需允许跨线程使用。
        return {"connect_args": {"check_same_thread": False}}

    kwargs = {
        "pool_pre_ping": True,
        "pool_recycle": int(os.getenv("DB_POOL_RECYCLE", "3600")),
        "pool_size": int(os.getenv("DB_POOL_SIZE", "10")),
        "max_overflow": int(os.getenv("DB_MAX_OVERFLOW", "20")),
        "pool_timeout": int(os.getenv("DB_POOL_TIMEOUT", "30")),
    }
    if IS_MYSQL and "charset=" not in DATABASE_URL:
        # URL 未显式带 charset 时兜底，避免中文/emoji 落库变成 ?
        kwargs["connect_args"] = {"charset": "utf8mb4"}
    return kwargs


engine = create_engine(DATABASE_URL, echo=False, future=True, **_engine_kwargs())


if IS_SQLITE:
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _connection_record):
        """SQLite 并发优化：WAL 允许读写并行，busy_timeout 避免高峰期 'database is locked'。"""
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def init_db() -> None:
    """建表（仅供本地零配置跑通与单元测试）。

    生产用 Alembic：`alembic upgrade head`（脚本在 migrations/）。
    原因是 create_all 只补建缺失的表，已存在表的列变更它一概不管——
    加字段、改长度、加索引都不会同步，久了库结构就和 models.py 悄悄分叉。

    已有数据的库首次接入迁移，用 `alembic stamp head` 标记当前版本，
    不要直接 upgrade（表已存在会冲突）。
    """
    Base.metadata.create_all(bind=engine)


def get_db():
    """FastAPI 依赖注入用：with Depends(get_db)。"""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
