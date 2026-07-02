"""Environment-backed settings for local demo services."""
from __future__ import annotations

import os
from functools import lru_cache


class Settings:
    DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")
    DEEPSEEK_BASE_URL: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    DEEPSEEK_MODEL: str = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    LLM_STUB_MODE: bool = os.getenv("LLM_STUB_MODE", "1") == "1"

    EMBEDDING_STUB_MODE: bool = os.getenv("EMBEDDING_STUB_MODE", "1") == "1"
    EMBEDDING_API_KEY: str = os.getenv("EMBEDDING_API_KEY", "")
    EMBEDDING_BASE_URL: str = os.getenv(
        "EMBEDDING_BASE_URL", "https://open.bigmodel.cn/api/paas/v4"
    )
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "embedding-3")
    EMBEDDING_DIM: int = int(os.getenv("EMBEDDING_DIM", "256"))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
