"""异步任务队列（arq）：把烧时间的 LLM 匹配从请求线程里挪出去。

**为什么只挪 /matches/refresh 这一个接口。** 爬虫已经有 systemd timer 在跑，
再塞进队列只是把同一件事换个地方执行，白白多一个要运维的进程；
而 `/matches/refresh` 是用户点一下就在请求线程里串行调几十次 DeepSeek：
几十秒白屏、网关一超时这次调用的钱照付、按钮还能重复点。这才是队列解决的问题。

**降级原则与 ratelimit 一致：Redis 连不上时不报错，退回同步执行。**
异步是体验优化，不是业务本身——不能因为队列挂了就让用户连匹配都跑不了。
入队失败返回 None，由调用方决定怎么兜底。

进度不用 arq 自带的任务状态：它只能告诉你"排队中/执行中/完成"，
而用户想看的是"评到第几个岗位了"。所以状态自己写一个 Redis 哈希，
arq 只负责队列和 worker 生命周期这两件它做得比手写好的事。
"""
from __future__ import annotations

import asyncio
import logging
import os

from services import ratelimit

logger = logging.getLogger("tasks")

REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")

# 任务状态保留时长。够用户轮询完拿到结果即可，不是持久化存储。
TASK_TTL_SEC = int(os.getenv("TASK_TTL_SEC", "3600"))
# 单个任务最长执行时间。几十个岗位逐个调模型可能要几分钟，
# 设太短会在快跑完时被杀掉，那次调用的钱就白花了。
JOB_TIMEOUT_SEC = int(os.getenv("TASK_JOB_TIMEOUT_SEC", "600"))

_pool = None
_pool_failed = False


def _key(task_id: str) -> str:
    return f"task:refresh:{task_id}"


def set_state(task_id: str, **fields) -> None:
    """写任务状态。Redis 不可用时静默跳过——状态丢失不该让任务本身失败。"""
    client = ratelimit.get_client()
    if client is None:
        return
    try:
        client.hset(_key(task_id), mapping={k: str(v) for k, v in fields.items()})
        client.expire(_key(task_id), TASK_TTL_SEC)
    except Exception as exc:  # noqa: BLE001 - 状态写失败不影响任务执行
        logger.warning("task state write failed",
                       extra={"extra_fields": {"task_id": task_id, "error": str(exc)}})


# 数值字段单独列出来做类型还原：Redis 哈希里一切都是字符串，
# 前端拿到 "12" 和 12 的行为不一样（进度条算比例会变字符串拼接）。
_INT_FIELDS = ("done", "total", "rules", "jobs", "new_matches")


def read_state(task_id: str) -> dict | None:
    client = ratelimit.get_client()
    if client is None:
        return None
    try:
        raw = client.hgetall(_key(task_id))
    except Exception as exc:  # noqa: BLE001
        logger.warning("task state read failed",
                       extra={"extra_fields": {"task_id": task_id, "error": str(exc)}})
        return None
    if not raw:
        return None
    state = dict(raw)
    for field in _INT_FIELDS:
        if field in state:
            try:
                state[field] = int(state[field])
            except ValueError:
                pass
    return state


async def _get_pool():
    """惰性建 arq 连接池。失败只记一次日志，之后静默走同步兜底。"""
    global _pool, _pool_failed
    if _pool is not None or _pool_failed:
        return _pool
    try:
        from arq import create_pool
        from arq.connections import RedisSettings

        settings = RedisSettings.from_dsn(REDIS_URL)
        # 默认会重试 5 次、每次等 1 秒，Redis 真挂了就是 5 秒白等在请求里。
        # 这里要的是"快速判定不可用然后同步兜底"。
        settings.conn_timeout = 1
        settings.conn_retries = 1
        _pool = await create_pool(settings)
    except Exception as exc:  # noqa: BLE001 - 含 arq 未安装，一律降级
        _pool_failed = True
        logger.warning("arq unavailable, refresh falls back to sync",
                       extra={"extra_fields": {"error": str(exc)}})
    return _pool


def reset_pool_for_tests() -> None:
    global _pool, _pool_failed
    _pool = None
    _pool_failed = False


async def enqueue_refresh(user_id: str) -> str | None:
    """把一次匹配刷新入队。返回任务 ID；队列不可用时返回 None。"""
    pool = await _get_pool()
    if pool is None:
        return None
    try:
        job = await pool.enqueue_job("refresh_matches", user_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("enqueue failed, falls back to sync",
                       extra={"extra_fields": {"error": str(exc)}})
        return None
    if job is None:  # 同 job_id 已在队列里，arq 返回 None
        return None
    # 立刻落一条 queued 状态：既让前端第一次轮询就有东西可读，
    # 也把归属写死，防止拿到别人的 task_id 就能读别人的结果。
    set_state(job.job_id, status="queued", user_id=user_id, done=0, total=0)
    return job.job_id


# ---------------- worker 侧 ----------------

def _run_blocking(task_id: str, user_id: str) -> dict:
    """在线程里跑同步的 SQLAlchemy 管道，别阻塞 worker 的事件循环。"""
    from database import SessionLocal
    from services import pipeline

    db = SessionLocal()
    try:
        return pipeline.run_pipeline(
            db, user_id=user_id,
            on_progress=lambda done, total: set_state(task_id, done=done, total=total),
        )
    finally:
        db.close()


async def refresh_matches(ctx, user_id: str) -> dict:
    task_id = ctx["job_id"]
    set_state(task_id, status="running")
    try:
        stats = await asyncio.to_thread(_run_blocking, task_id, user_id)
    except Exception as exc:  # noqa: BLE001 - 要把失败原因交给前端，然后照常抛给 arq
        set_state(task_id, status="failed", error=f"{type(exc).__name__}: {exc}")
        logger.exception("refresh task failed",
                         extra={"extra_fields": {"task_id": task_id, "user_id": user_id}})
        raise
    set_state(task_id, status="done", **stats)
    return stats


try:  # arq 只在 worker 进程里是硬依赖；API 进程缺了它也要能起来
    from arq.connections import RedisSettings as _RedisSettings

    _WORKER_REDIS = _RedisSettings.from_dsn(REDIS_URL)
except Exception:  # noqa: BLE001
    _WORKER_REDIS = None


async def _on_startup(ctx) -> None:
    """启动时打印连到哪个库。

    实测踩过：worker 没加载 .env，于是连到了默认的 SQLite，而 API 在 MySQL 上。
    进程不报错、任务也"成功"，只是每次都返回 0 个匹配——
    **连错库是静默失败，比崩溃难查得多。** 把目标打在第一行日志里，
    这种失配一眼就能看见。生产由 systemd 的 EnvironmentFile 保证同源。
    """
    from observability import setup_logging

    setup_logging()

    from config import settings

    label = settings.DATABASE_URL
    try:  # 日志里不能出现数据库密码
        from sqlalchemy.engine import make_url

        label = make_url(settings.DATABASE_URL).render_as_string(hide_password=True)
    except Exception:  # noqa: BLE001
        label = label.split("@")[-1]
    logger.info("worker started", extra={"extra_fields": {
        "database": label,
        "llm_stub_mode": settings.LLM_STUB_MODE,
        "redis": REDIS_URL.rsplit("@", 1)[-1],
    }})


class WorkerSettings:
    """启动 worker：`arq services.tasks.WorkerSettings`（cwd 为 backend/）。"""

    functions = [refresh_matches]
    on_startup = _on_startup
    redis_settings = _WORKER_REDIS
    job_timeout = JOB_TIMEOUT_SEC
    # 单实例够用；调大要先算 DeepSeek 并发和数据库连接池（见 database.py 的容量说明）。
    max_jobs = 4
    # 失败不自动重试：这些任务每次都真金白银调模型，
    # 自动重跑等于自动重复付费，且失败原因多半是配置或额度，重试也不会好。
    max_tries = 1
