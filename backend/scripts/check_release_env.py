"""Check backend environment readiness for public Web release.

This script intentionally prints only status and missing keys, never secret values.
Run it on the server from /opt/teacher-job-api/backend or locally from the backend folder:

    python3 scripts/check_release_env.py .env
"""
from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit


REQUIRED_FOR_RELEASE = [
    "MYSQL_ROOT_PASSWORD",
    "MYSQL_PASSWORD",
    "SESSION_SECRET",
    "ADMIN_API_TOKEN",
]

OPTIONAL_REAL_SERVICE_GROUPS = {
    "微信小程序登录": {
        "flag": None,
        "keys": ["WECHAT_APPID", "WECHAT_SECRET"],
    },
    "真实 AI 匹配": {
        "flag": ("LLM_STUB_MODE", "0"),
        "keys": ["DEEPSEEK_API_KEY"],
    },
    "真实邮件投递": {
        "flag": ("MAILER_DRY_RUN", "0"),
        "keys": ["SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM"],
    },
    "COS 简历存储": {
        "flag": None,
        "keys": ["COS_REGION", "COS_BUCKET", "COS_SECRET_ID", "COS_SECRET_KEY"],
    },
}


def parse_env(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip().strip('"').strip("'")
    return data


def masked_state(value: str | None) -> str:
    if not value:
        return "未填写"
    if "change-me" in value or value in {"dev-insecure-secret-change-me", "your-secret"}:
        return "仍是示例值"
    return "已填写"


def main() -> int:
    env_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".env")
    if not env_path.exists():
        print(f"未找到环境变量文件：{env_path}")
        print("先复制 .env.example 为 .env，并填写真实配置。")
        return 1

    env = parse_env(env_path)
    issues: list[str] = []
    warnings: list[str] = []

    if env.get("AUTH_DEV_MODE", "1") != "0":
        issues.append("AUTH_DEV_MODE 仍是开发模式，正式上线应设为 0")

    database_url = env.get("DATABASE_URL", "")
    if not database_url:
        issues.append("DATABASE_URL 未填写")
    elif database_url.startswith("sqlite"):
        issues.append("DATABASE_URL 仍指向 SQLite，生产应使用 MySQL（单文件库无法支撑并发写入与在线备份）")
    elif database_url.startswith("mysql"):
        if "charset=utf8mb4" not in database_url:
            issues.append("MySQL 连接串缺少 charset=utf8mb4，中文与 emoji 会写入失败")
        if "change-me" in database_url:
            issues.append("DATABASE_URL 仍是示例密码，请改成真实凭据")
        database_password = unquote(urlsplit(database_url).password or "")
        mysql_password_ready = masked_state(env.get("MYSQL_PASSWORD")) == "已填写"
        if "change-me" not in database_url and mysql_password_ready and database_password != env["MYSQL_PASSWORD"]:
            issues.append("DATABASE_URL 密码与 MYSQL_PASSWORD 不一致，应用将无法连接容器中的 MySQL")

    for key in REQUIRED_FOR_RELEASE:
        state = masked_state(env.get(key))
        if state != "已填写":
            issues.append(f"{key} {state}")

    for key in ("MYSQL_ROOT_PASSWORD", "MYSQL_PASSWORD", "SESSION_SECRET", "ADMIN_API_TOKEN"):
        if env.get(key) and len(env[key]) < 24:
            issues.append(f"{key} 太短，建议至少 24 位以上随机字符串")

    for name, group in OPTIONAL_REAL_SERVICE_GROUPS.items():
        flag = group["flag"]
        keys = group["keys"]
        if flag is not None:
            flag_key, ready_value = flag
            if env.get(flag_key) != ready_value:
                warnings.append(f"{name} 未启用：{flag_key}={env.get(flag_key, '未填写')}")
                continue
        missing = [key for key in keys if not env.get(key)]
        if missing:
            warnings.append(f"{name} 配置不完整：{', '.join(missing)}")

    print("后端上线环境检查：")
    if issues:
        print("必须处理：")
        for issue in issues:
            print(f"- {issue}")
    else:
        print("- 必填项通过")

    if warnings:
        print("可选增强：")
        for warning in warnings:
            print(f"- {warning}")

    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
