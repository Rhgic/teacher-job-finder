"""文本向量化。默认占位实现（无需 Key）；EMBEDDING_STUB_MODE=0 时走智谱 embedding-3。"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import time

from config import settings
from services import ratelimit

logger = logging.getLogger("embedding")

DIM = settings.EMBEDDING_DIM

# 智谱单次请求有条数上限，超过直接 400；全量建索引必须分批。
EMBED_BATCH_SIZE = int(os.getenv("EMBEDDING_BATCH_SIZE", "32"))
EMBED_MAX_ATTEMPTS = 3
EMBED_BACKOFF_BASE_SEC = 1.0


def _stub_one(text: str) -> list[float]:
    """占位：字符二元组特征哈希 + 带符号 + L2 归一化。

    本质是关键词重叠检索，够把 RAG 链路跑通和演示；接真实模型后整体替换。
    """
    vec = [0.0] * DIM
    t = (text or "").strip()
    tokens = [t[i:i + 2] for i in range(len(t) - 1)] or ([t] if t else [])
    for tok in tokens:
        h = int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16)
        vec[h % DIM] += 1.0 if (h >> 8) % 2 == 0 else -1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _cache_key(text: str) -> str:
    """键里带模型与维度：换模型或换维度后必须重算，不能复用旧向量。"""
    raw = f"{settings.EMBEDDING_MODEL}|{settings.EMBEDDING_DIM}|{text}"
    return "emb:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _sleep_backoff(attempt: int, kind: str, detail: str) -> None:
    if attempt >= EMBED_MAX_ATTEMPTS - 1:
        logger.warning("embedding_failed", extra={"extra_fields": {
            "kind": kind, "detail": detail, "attempts": attempt + 1}})
        return
    delay = EMBED_BACKOFF_BASE_SEC * (2 ** attempt)
    logger.warning("embedding_retry", extra={"extra_fields": {
        "kind": kind, "detail": detail, "attempt": attempt + 1, "sleep_sec": delay}})
    time.sleep(delay)


def _post_batch(texts: list[str]) -> list[list[float]]:
    """调一次智谱 embeddings。5xx 与超时重试，4xx 立即抛出。"""
    import httpx

    url = f"{settings.EMBEDDING_BASE_URL}/embeddings"
    headers = {"Authorization": f"Bearer {settings.EMBEDDING_API_KEY}"}
    payload = {
        "model": settings.EMBEDDING_MODEL,
        "input": texts,
        # embedding-3 支持指定输出维度；显式传，避免默认维度与库中已存的不一致
        "dimensions": settings.EMBEDDING_DIM,
    }
    last_exc: Exception | None = None
    for attempt in range(EMBED_MAX_ATTEMPTS):
        started = time.perf_counter()
        try:
            resp = httpx.post(url, headers=headers, json=payload,
                              timeout=httpx.Timeout(60.0, connect=10.0))
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_exc = exc
            _sleep_backoff(attempt, "network", str(exc))
            continue

        if resp.status_code >= 500:
            last_exc = httpx.HTTPStatusError(
                f"server error {resp.status_code}", request=resp.request, response=resp)
            _sleep_backoff(attempt, f"http_{resp.status_code}", resp.text[:120])
            continue

        resp.raise_for_status()
        body = resp.json()
        usage = body.get("usage") or {}
        ratelimit.record_tokens(int(usage.get("total_tokens") or 0))
        logger.info("embedding_call", extra={"extra_fields": {
            "model": settings.EMBEDDING_MODEL,
            "batch_size": len(texts),
            "total_tokens": usage.get("total_tokens"),
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            "attempt": attempt + 1,
        }})
        # 接口不保证按输入顺序返回，必须按 index 归位
        data = sorted(body["data"], key=lambda d: d["index"])
        return [d["embedding"] for d in data]

    raise last_exc if last_exc else RuntimeError("智谱 embedding 调用失败")


def _zhipu_embed(texts: list[str]) -> list[list[float]]:
    """智谱 embedding-3：分批请求 + 结果缓存。

    reindex 是全量重建，同一段公告切片会被反复向量化；
    缓存能把重复建索引的开销降到接近零。
    """
    results: list[list[float] | None] = [None] * len(texts)
    misses: list[int] = []

    for i, text in enumerate(texts):
        cached = ratelimit.cache_get(_cache_key(text))
        if cached:
            results[i] = json.loads(cached)
        else:
            misses.append(i)

    for start in range(0, len(misses), EMBED_BATCH_SIZE):
        idxs = misses[start:start + EMBED_BATCH_SIZE]
        vectors = _post_batch([texts[i] for i in idxs])
        for i, vec in zip(idxs, vectors, strict=True):
            results[i] = vec
            ratelimit.cache_set(_cache_key(texts[i]), json.dumps(vec))

    return [r for r in results if r is not None]


def embed(texts: list[str]) -> list[list[float]]:
    """统一向量化入口。上层不关心占位/真实实现。"""
    if not texts:
        return []
    if settings.EMBEDDING_STUB_MODE:
        return [_stub_one(t) for t in texts]
    return _zhipu_embed(texts)
