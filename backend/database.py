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

    连接池容量与超时按压测结果调整（详见 backend/README.md「容量」一节）：
    路由是同步的，Session 从首次查询一直持有连接到请求结束，
    因此并发请求数一旦超过池容量就会排队。压测实测原配置（10+20，超时 30s）
    在 128 并发下退化为全部请求等满 60 秒、日志里 360 次 QueuePool 超时——
    这是"慢性死亡"而非快速失败，比直接拒绝更糟。

    改法有两处：
    - 提高容量到 20+30=50。MySQL max_connections 默认 151，
      单实例占 50 仍留有余量；但这也意味着**最多并排跑 3 个实例**，
      再多要先调大 MySQL 侧上限。
    - 把等待超时压到 5 秒。宁可让超载请求快速失败让客户端重试，
      也不要让用户干等一分钟——与 Redis 那层"降级优先于保护"同一原则。

    **容量与超时对所有后端一视同仁，不能只配给 MySQL。**
    这里原先对 SQLite 直接 `return {"connect_args": ...}`，理由写的是
    "SQLite 是本地文件，没有网络连接池语义"。这个说法站不住：
    文件型 SQLite 在 SQLAlchemy 里照样走 QueuePool，跳过这几个参数
    只会让 SQLAlchemy 的默认值生效——**pool_size=5、max_overflow=10、
    pool_timeout=30**。于是不带 DATABASE_URL 启动（也就是 README 教的
    默认开发命令）时，上面那套"5 秒快速失败"根本没生效，
    过载表现回到 30 秒挂起，正是这次调整想消灭的"慢性死亡"。
    2026-08-10 实测：56 并发下 P50 30.0 秒、QPS 3.7。
    """
    kwargs: dict = {
        "pool_size": int(os.getenv("DB_POOL_SIZE", "20")),
        "max_overflow": int(os.getenv("DB_MAX_OVERFLOW", "30")),
        "pool_timeout": int(os.getenv("DB_POOL_TIMEOUT", "5")),
    }

    if IS_SQLITE:
        # 内存库用的是 StaticPool / SingletonThreadPool，不接受容量参数，
        # 传进去会直接 TypeError；它本来也只有一条连接，无池可言。
        if ":memory:" in DATABASE_URL:
            return {"connect_args": {"check_same_thread": False}}
        kwargs["connect_args"] = {"check_same_thread": False}
        return kwargs

    # 以下两项只对网络型数据库有意义
    kwargs["pool_pre_ping"] = True
    kwargs["pool_recycle"] = int(os.getenv("DB_POOL_RECYCLE", "3600"))
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
