"""Alembic 运行环境。

与项目的两条约定对齐：
1. 连接串统一从 DATABASE_URL 环境变量取（和 database.py 同源），
   不在 alembic.ini 里写死——否则本地、CI、生产会各写一份，迟早不一致。
2. target_metadata 直接挂 models.Base，autogenerate 才能对比出模型与库的差异。
"""
import os
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool

from alembic import context

# migrations/ 在 backend/ 下，要把 backend/ 加进 sys.path 才 import 得到项目模块
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from models import Base  # noqa: E402  —— 必须在 sys.path 设好之后导入

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url() -> str:
    """优先用环境变量；缺省值与 database.py 保持一致。"""
    return os.getenv("DATABASE_URL", "sqlite:///./teacher_jobs.db")


def run_migrations_offline() -> None:
    """离线模式：只生成 SQL 文本，不连库。用于让 DBA 审阅将要执行的变更。"""
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式：连库执行迁移。"""
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = get_url()

    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # 默认只比对列的增删，不比对类型变更；开启后改长度/类型也能被 autogenerate 发现
            compare_type=True,
            # SQLite 不支持大部分 ALTER TABLE，batch 模式会用"建新表-拷数据-换名"绕过
            render_as_batch=connection.dialect.name == "sqlite",
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
