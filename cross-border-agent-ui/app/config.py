"""环境变量与启动配置。

单一来源：所有模块都从 get_settings() 取配置，不各自读 os.environ，
否则测试里改一处、生产读另一处，很难查。
"""

from functools import lru_cache
from typing import ClassVar

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # HS256 的安全性直接取决于密钥长度。PyJWT 对短密钥只发 InsecureKeyLengthWarning，
    # 警告很容易被忽略，所以这里直接拒绝启动——配置错误该在启动时炸，
    # 而不是等到有人用弱密钥签出的 token 冒充管理员时才发现。
    MIN_JWT_SECRET_BYTES: ClassVar[int] = 32

    database_url: str = "postgresql+psycopg://cbagent:cbagent@localhost:5433/cbagent"

    # 无默认值：必须由环境显式提供。留一个"能跑"的弱默认，等于给了所有人
    # 伪造 admin token 的能力——而且这种默认最容易被原样带上线。
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60

    seed_password: str = "demo1234"

    # 留空即使用本地确定性草稿生成器；Demo 不需要任何外部 Key。
    deepseek_api_key: str = ""
    deepseek_base: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    llm_timeout_seconds: float = 20.0

    app_env: str = "dev"
    log_level: str = "INFO"

    # 单条买家消息长度上限：既防滥用，也避免把超长文本送进模型。
    max_message_chars: int = 2000

    @field_validator("jwt_secret")
    @classmethod
    def _validate_jwt_secret(cls, v: str) -> str:
        if len(v.encode()) < Settings.MIN_JWT_SECRET_BYTES:
            raise ValueError(
                f"JWT_SECRET 至少需要 {Settings.MIN_JWT_SECRET_BYTES} 字节，"
                f"当前 {len(v.encode())} 字节。请用 `openssl rand -hex 32` 生成。"
            )
        return v

    @property
    def llm_enabled(self) -> bool:
        return bool(self.deepseek_api_key.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
