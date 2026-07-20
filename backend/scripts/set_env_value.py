"""Safely update one key in a .env file, with backup.

Usage:
    python3 scripts/set_env_value.py .env WECHAT_SECRET your-secret
"""
from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path


ALLOWED_KEYS = {
    "AUTH_DEV_MODE",
    "WECHAT_APPID",
    "WECHAT_SECRET",
    "SESSION_SECRET",
    "ADMIN_API_TOKEN",
    "LLM_STUB_MODE",
    "DEEPSEEK_API_KEY",
    "MAILER_DRY_RUN",
    "SMTP_HOST",
    "SMTP_PORT",
    "SMTP_USER",
    "SMTP_PASSWORD",
    "SMTP_FROM",
    "COS_REGION",
    "COS_BUCKET",
    "COS_SECRET_ID",
    "COS_SECRET_KEY",
    "DATABASE_URL",
}


def quote_value(value: str) -> str:
    if not value:
        return ""
    if any(ch.isspace() for ch in value) or "#" in value or '"' in value or "'" in value:
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value


def set_env_value(path: Path, key: str, value: str) -> None:
    if key not in ALLOWED_KEYS:
        allowed = ", ".join(sorted(ALLOWED_KEYS))
        raise ValueError(f"不允许修改这个键：{key}。可修改：{allowed}")
    if not path.exists():
        raise FileNotFoundError(f"未找到环境变量文件：{path}")

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    backup = path.with_name(f"{path.name}.bak.{timestamp}")
    shutil.copy2(path, backup)

    lines = path.read_text(encoding="utf-8").splitlines()
    rendered = f"{key}={quote_value(value)}"
    replaced = False
    next_lines: list[str] = []
    for line in lines:
        if line.strip().startswith(f"{key}="):
            next_lines.append(rendered)
            replaced = True
        else:
            next_lines.append(line)
    if not replaced:
        next_lines.append(rendered)
    path.write_text("\n".join(next_lines) + "\n", encoding="utf-8")
    print(f"已更新 {key}，备份：{backup}")


def main() -> int:
    if len(sys.argv) != 4:
        print("Usage: python3 scripts/set_env_value.py .env KEY value")
        return 2
    try:
        set_env_value(Path(sys.argv[1]), sys.argv[2], sys.argv[3])
    except Exception as exc:  # noqa: BLE001 - CLI should show plain Chinese-friendly error.
        print(f"更新失败：{exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
