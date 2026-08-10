"""连接池参数必须真的传到 engine 上。

背景：`_engine_kwargs()` 曾对 SQLite 直接返回 `{"connect_args": ...}`，
把 pool_size / max_overflow / pool_timeout 全跳过。文件型 SQLite 在
SQLAlchemy 里仍然走 QueuePool，跳过的后果不是"没有池"，而是**用了
SQLAlchemy 的默认池**：size=5、overflow=10、timeout=30。

于是"等待超时压到 5 秒、过载快速失败"这条设计在默认开发路径上完全没生效，
56 并发实测 P50 30 秒、QPS 3.7（2026-08-10）。
这类 bug 不会被功能测试发现——接口全都返回 200，只是慢。
"""
import importlib
import os

import pytest


def _fresh_database(monkeypatch, url: str):
    """按给定 DATABASE_URL 重新导入 database 模块，拿到新建的 engine。"""
    monkeypatch.setenv("DATABASE_URL", url)
    import database
    return importlib.reload(database)


@pytest.fixture
def restore_database():
    """用例结束后把模块还原成进程原本的配置，避免污染后续用例。"""
    yield
    import database
    importlib.reload(database)


def test_sqlite_file_engine_applies_pool_timeout(tmp_path, monkeypatch, restore_database):
    """文件型 SQLite 必须拿到配置的 pool_timeout，而不是 SQLAlchemy 默认的 30。"""
    db = _fresh_database(monkeypatch, f"sqlite:///{tmp_path/'t.db'}")

    assert db.engine.pool._timeout == 5, (
        "SQLite 没拿到 pool_timeout，过载时会挂满 30 秒而不是 5 秒快速失败"
    )
    assert db.engine.pool.size() == 20
    assert db.engine.pool._max_overflow == 30


def test_sqlite_pool_honours_env_override(tmp_path, monkeypatch, restore_database):
    """环境变量要能覆盖，否则压测时没法调参对比。"""
    monkeypatch.setenv("DB_POOL_TIMEOUT", "2")
    monkeypatch.setenv("DB_POOL_SIZE", "7")
    db = _fresh_database(monkeypatch, f"sqlite:///{tmp_path/'t.db'}")

    assert db.engine.pool._timeout == 2
    assert db.engine.pool.size() == 7


def test_memory_sqlite_skips_pool_args(monkeypatch, restore_database):
    """内存库不接受容量参数，传了会 TypeError——这条守住那个分支。"""
    db = _fresh_database(monkeypatch, "sqlite:///:memory:")

    assert db.engine is not None
    assert "pool_size" not in db._engine_kwargs()


def test_mysql_keeps_pre_ping_and_recycle(monkeypatch, restore_database):
    """网络型数据库特有的两项不能因为重构被顺手删掉。

    只检查参数字典，不建真实连接——CI 里没有 MySQL。
    """
    monkeypatch.setenv("DATABASE_URL", "mysql+pymysql://u:p@127.0.0.1:3306/x")
    import database
    monkeypatch.setattr(database, "DATABASE_URL", os.environ["DATABASE_URL"])
    monkeypatch.setattr(database, "IS_SQLITE", False)
    monkeypatch.setattr(database, "IS_MYSQL", True)

    kwargs = database._engine_kwargs()

    assert kwargs["pool_pre_ping"] is True
    assert kwargs["pool_recycle"] == 3600
    assert kwargs["pool_timeout"] == 5
    assert kwargs["connect_args"] == {"charset": "utf8mb4"}
