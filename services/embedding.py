"""Text embeddings. Stub mode is deterministic and works offline."""
from __future__ import annotations

import hashlib
import math

import httpx

from config import settings


def _stub_one(text: str) -> list[float]:
    vec = [0.0] * settings.EMBEDDING_DIM
    compact = (text or "").strip()
    tokens = [compact[i : i + 2] for i in range(len(compact) - 1)] or ([compact] if compact else [])
    for token in tokens:
        digest = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16)
        vec[digest % settings.EMBEDDING_DIM] += 1.0 if (digest >> 8) % 2 == 0 else -1.0
    norm = math.sqrt(sum(item * item for item in vec)) or 1.0
    return [item / norm for item in vec]


def _zhipu_embed(texts: list[str]) -> list[list[float]]:
    response = httpx.post(
        f"{settings.EMBEDDING_BASE_URL}/embeddings",
        headers={"Authorization": f"Bearer {settings.EMBEDDING_API_KEY}"},
        json={"model": settings.EMBEDDING_MODEL, "input": texts},
        timeout=60,
    )
    response.raise_for_status()
    data = sorted(response.json()["data"], key=lambda item: item["index"])
    return [item["embedding"] for item in data]


def embed(texts: list[str]) -> list[list[float]]:
    if settings.EMBEDDING_STUB_MODE:
        return [_stub_one(text) for text in texts]
    return _zhipu_embed(texts)
