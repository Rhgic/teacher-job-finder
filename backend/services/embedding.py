"""文本向量化。默认占位实现（无需 Key）；EMBEDDING_STUB_MODE=0 时走智谱 embedding-3。"""
from __future__ import annotations

import hashlib
import math

from config import settings

DIM = settings.EMBEDDING_DIM


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


def _zhipu_embed(texts: list[str]) -> list[list[float]]:
    """智谱 embedding-3（OpenAI 兼容）。EMBEDDING_STUB_MODE=0 且配好 Key 时启用。"""
    import httpx

    resp = httpx.post(
        f"{settings.EMBEDDING_BASE_URL}/embeddings",
        headers={"Authorization": f"Bearer {settings.EMBEDDING_API_KEY}"},
        json={"model": settings.EMBEDDING_MODEL, "input": texts},
        timeout=60,
    )
    resp.raise_for_status()
    data = sorted(resp.json()["data"], key=lambda d: d["index"])
    return [d["embedding"] for d in data]


def embed(texts: list[str]) -> list[list[float]]:
    """统一向量化入口。上层不关心占位/真实实现。"""
    if settings.EMBEDDING_STUB_MODE:
        return [_stub_one(t) for t in texts]
    return _zhipu_embed(texts)
