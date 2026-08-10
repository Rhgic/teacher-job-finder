import asyncio
from types import SimpleNamespace

from services import tasks

_enqueue_refresh = tasks.enqueue_refresh


def test_enqueue_refresh_deduplicates_by_user(monkeypatch):
    class FakePool:
        def __init__(self):
            self.ids = set()
            self.calls = []

        async def enqueue_job(self, function, user_id, **kwargs):
            self.calls.append((function, user_id, kwargs))
            job_id = kwargs["_job_id"]
            if job_id in self.ids:
                return None
            self.ids.add(job_id)
            return SimpleNamespace(job_id=job_id)

    pool = FakePool()

    async def get_pool():
        return pool

    monkeypatch.setattr(tasks, "_get_pool", get_pool)
    monkeypatch.setattr(tasks, "set_state", lambda *_args, **_kwargs: None)

    first = asyncio.run(_enqueue_refresh("user-1"))
    second = asyncio.run(_enqueue_refresh("user-1"))

    assert first.task_id == second.task_id == "refresh:user-1"
    assert first.is_new is True
    assert second.is_new is False
    assert pool.calls[0][2]["_job_id"] == "refresh:user-1"
    assert pool.calls[0][2]["_defer_by"] == 1
