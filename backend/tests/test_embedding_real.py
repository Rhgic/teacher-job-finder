"""真实 embedding 路径测试（分批、缓存、重试、维度守卫）。

不连真实智谱接口，用假响应覆盖分支。
这些逻辑都是"切到真实模型才会暴露"的那一类：
stub 模式下 embed() 是纯本地计算，永远测不出批量上限和维度不一致。
"""
import json

import httpx
import pytest

from services import embedding, ratelimit


class _Resp:
    def __init__(self, vectors, status_code=200, shuffled=False):
        self.status_code = status_code
        self._vectors = vectors
        self._shuffled = shuffled
        self.request = httpx.Request("POST", "https://open.bigmodel.cn/api/paas/v4/embeddings")
        self.text = "err"

    def json(self):
        data = [{"index": i, "embedding": v} for i, v in enumerate(self._vectors)]
        if self._shuffled:
            data = list(reversed(data))
        return {"data": data, "usage": {"total_tokens": 10}}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("err", request=self.request, response=self)


@pytest.fixture(autouse=True)
def _real_mode(monkeypatch):
    """切到真实模式并去掉退避等待。Redis 由 conftest 统一置为不可用。"""
    monkeypatch.setattr(embedding.settings, "EMBEDDING_STUB_MODE", False)
    monkeypatch.setattr(embedding.settings, "EMBEDDING_DIM", 4)
    monkeypatch.setattr(embedding.time, "sleep", lambda _s: None)


def test_splits_into_batches(monkeypatch):
    """一次性提交全部切片会超过接口条数上限，必须分批。"""
    monkeypatch.setattr(embedding, "EMBED_BATCH_SIZE", 2)
    batches: list[int] = []

    def fake_post(*a, **k):
        n = len(k["json"]["input"])
        batches.append(n)
        return _Resp([[0.1] * 4 for _ in range(n)])

    monkeypatch.setattr(httpx, "post", fake_post)
    out = embedding.embed([f"chunk-{i}" for i in range(5)])
    assert len(out) == 5
    assert batches == [2, 2, 1]


def test_reorders_by_index(monkeypatch):
    """接口不保证按输入顺序返回，必须按 index 归位，否则向量张冠李戴。"""
    vectors = [[1.0, 0, 0, 0], [0, 1.0, 0, 0], [0, 0, 1.0, 0]]
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _Resp(vectors, shuffled=True))
    assert embedding.embed(["a", "b", "c"]) == vectors


def test_passes_dimensions_explicitly(monkeypatch):
    """显式传 dimensions，避免服务端默认维度与库中已存的不一致。"""
    seen: list[dict] = []

    def fake_post(*a, **k):
        seen.append(k["json"])
        return _Resp([[0.0] * 4])

    monkeypatch.setattr(httpx, "post", fake_post)
    embedding.embed(["x"])
    assert seen[0]["dimensions"] == 4


def test_retries_on_server_error(monkeypatch):
    calls = {"n": 0}

    def fake_post(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            return _Resp([], status_code=503)
        return _Resp([[0.5] * 4])

    monkeypatch.setattr(httpx, "post", fake_post)
    assert embedding.embed(["x"]) == [[0.5] * 4]
    assert calls["n"] == 2


def test_does_not_retry_client_error(monkeypatch):
    calls = {"n": 0}

    def fake_post(*a, **k):
        calls["n"] += 1
        return _Resp([], status_code=401)

    monkeypatch.setattr(httpx, "post", fake_post)
    with pytest.raises(httpx.HTTPStatusError):
        embedding.embed(["x"])
    assert calls["n"] == 1


def test_cache_avoids_repeat_calls(monkeypatch):
    """reindex 是全量重建，同一段文本会被反复向量化，缓存直接省钱。"""
    store: dict[str, str] = {}
    monkeypatch.setattr(ratelimit, "cache_get", lambda k: store.get(k))
    monkeypatch.setattr(ratelimit, "cache_set", lambda k, v: store.__setitem__(k, v))
    calls = {"n": 0}

    def fake_post(*a, **k):
        calls["n"] += 1
        n = len(k["json"]["input"])
        return _Resp([[0.25] * 4 for _ in range(n)])

    monkeypatch.setattr(httpx, "post", fake_post)
    first = embedding.embed(["同一段公告"])
    second = embedding.embed(["同一段公告"])
    assert first == second
    assert calls["n"] == 1


def test_cache_key_changes_with_dimension(monkeypatch):
    """换维度后不能复用旧向量，否则新旧维度混在库里。"""
    key_4 = embedding._cache_key("t")
    monkeypatch.setattr(embedding.settings, "EMBEDDING_DIM", 1024)
    assert embedding._cache_key("t") != key_4


def test_empty_input_makes_no_call(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("不该发请求")

    monkeypatch.setattr(httpx, "post", boom)
    assert embedding.embed([]) == []


def test_retrieve_skips_mismatched_dimensions(tmp_path, monkeypatch):
    """切换模型后忘了重建索引：旧维度向量必须跳过而不是算出错误分数。"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from models import Base, DocChunk
    from services import rag_qa

    engine = create_engine(f"sqlite:///{tmp_path / 't.db'}", future=True,
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)

    with Session() as db:
        db.add(DocChunk(source_type="job", source_id="j1", source_title="旧公告",
                        content="报名材料包括身份证", chunk_index=0,
                        embedding=json.dumps([0.5] * 256)))   # 旧的 256 维
        db.add(DocChunk(source_type="job", source_id="j2", source_title="新公告",
                        content="报名材料包括学历证书", chunk_index=0,
                        embedding=json.dumps([0.5, 0.5, 0.5, 0.5])))  # 新的 4 维
        db.commit()

        monkeypatch.setattr(rag_qa.settings, "EMBEDDING_STUB_MODE", False)
        monkeypatch.setattr(rag_qa, "embed", lambda texts: [[0.5, 0.5, 0.5, 0.5]])
        monkeypatch.setattr(rag_qa, "MIN_SCORE", 0.0)

        chunks = rag_qa.retrieve(db, "报名要什么材料")

    assert [c.source_title for c in chunks] == ["新公告"]
