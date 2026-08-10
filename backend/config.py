"""集中配置（从环境变量读取，带开发默认值）。"""
import os
from functools import lru_cache


class Settings:
    # 数据库（database.py 也读这个变量）
    # 生产用 MySQL；默认值保留 SQLite 只为本地零配置跑通和单元测试。
    # scripts/check_release_env.py 会拦截"生产仍用 SQLite"的误配。
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./teacher_jobs.db")

    # DeepSeek（第二层 LLM 匹配 / 简历改写）
    DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")
    DEEPSEEK_BASE_URL: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    DEEPSEEK_MODEL: str = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    # 开发开关：为 1 时 LLM 用占位实现，无需 API Key 即可跑通全链路。
    # Codex 把真实 prompt 填好、配好 Key 后，设为 0 启用真实调用。
    LLM_STUB_MODE: bool = os.getenv("LLM_STUB_MODE", "1") == "1"

    # Embedding（RAG 检索用）。默认占位，无需 Key 即可跑通。
    EMBEDDING_STUB_MODE: bool = os.getenv("EMBEDDING_STUB_MODE", "1") == "1"
    EMBEDDING_API_KEY: str = os.getenv("EMBEDDING_API_KEY", "")
    EMBEDDING_BASE_URL: str = os.getenv("EMBEDDING_BASE_URL", "https://open.bigmodel.cn/api/paas/v4")
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "embedding-3")
    # 占位维度；接真实模型后改为其维度。
    EMBEDDING_DIM: int = int(os.getenv("EMBEDDING_DIM", "256"))

    # 发信（SMTP）
    SMTP_HOST: str = os.getenv("SMTP_HOST", "")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "465"))
    SMTP_USER: str = os.getenv("SMTP_USER", "")
    SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
    SMTP_FROM: str = os.getenv("SMTP_FROM", "")
    # 为 1 时不真正发信，只记录日志（开发用，避免误发）
    MAILER_DRY_RUN: bool = os.getenv("MAILER_DRY_RUN", "1") == "1"

    # 微信登录（jscode2session）
    WECHAT_APPID: str = os.getenv("WECHAT_APPID", "")
    WECHAT_SECRET: str = os.getenv("WECHAT_SECRET", "")
    # 会话令牌签名密钥（生产务必改成强随机值并保密）
    SESSION_SECRET: str = os.getenv("SESSION_SECRET", "dev-insecure-secret-change-me")
    # 为 1 时，无 Authorization 头则回退 demo 用户，便于本地联调；生产置 0
    AUTH_DEV_MODE: bool = os.getenv("AUTH_DEV_MODE", "1") == "1"
    # 管理接口令牌。生产环境用于保护爬虫、后台任务等非普通用户接口。
    ADMIN_API_TOKEN: str = os.getenv("ADMIN_API_TOKEN", "")

    # 用户 API Key 的加密主密钥（Fernet，32 字节 urlsafe-base64）。
    # 刻意**不给开发默认值**：给了默认值就等于所有开发机共用同一把密钥，
    # 而且忘记配置时不会有任何报错。缺失时 services/crypto.py 抛错、
    # 应用启动失败；测试由 tests/conftest.py 显式注入固定测试密钥。
    APP_ENCRYPTION_KEY: str = os.getenv("APP_ENCRYPTION_KEY", "")

    # 对象存储 COS（简历 PDF）；未配置则渲染到本地目录
    COS_REGION: str = os.getenv("COS_REGION", "")
    COS_BUCKET: str = os.getenv("COS_BUCKET", "")
    COS_SECRET_ID: str = os.getenv("COS_SECRET_ID", "")
    COS_SECRET_KEY: str = os.getenv("COS_SECRET_KEY", "")
    RESUME_OUTPUT_DIR: str = os.getenv("RESUME_OUTPUT_DIR", "./generated_resumes")

    # 数据库备份目录（备份脚本产物 + 运维状态展示）
    BACKUP_DIR: str = os.getenv("BACKUP_DIR", "./backups")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
