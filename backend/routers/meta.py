"""Meta/operations endpoints that expose non-sensitive readiness state."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from models import Job, SubRule

router = APIRouter(tags=["meta"])


def _configured(value: str) -> bool:
    return bool(value and "change-me" not in value and value != "dev-insecure-secret-change-me")


def _backup_status() -> dict:
    backup_dir = Path(settings.BACKUP_DIR)
    backups = []
    if backup_dir.exists() and backup_dir.is_dir():
        # *.sql.gz 是 MySQL（mysqldump）产物，*.sqlite3 是切库前的历史备份
        found = [item for pattern in ("*.sql.gz", "*.sqlite3") for item in backup_dir.glob(pattern)]
        backups = sorted(found, key=lambda item: item.stat().st_mtime, reverse=True)

    latest = backups[0] if backups else None
    latest_mtime = None
    latest_size_bytes = None
    if latest:
        stat = latest.stat()
        latest_mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
        latest_size_bytes = stat.st_size

    return {
        "configured": bool(settings.BACKUP_DIR),
        "count": len(backups),
        "latest_at": latest_mtime,
        "latest_file": latest.name if latest else None,
        "latest_size_bytes": latest_size_bytes,
        "ok": bool(backups),
    }


@router.get("/readiness")
def readiness(db: Session = Depends(get_db)):
    """Return non-secret launch readiness hints for operators and release checks."""
    job_count = db.scalar(select(func.count()).select_from(Job)) or 0
    active_rule_count = db.scalar(
        select(func.count()).select_from(SubRule).where(SubRule.is_active.is_(True))
    ) or 0
    latest_job_at = db.scalar(select(func.max(Job.crawled_at)))

    required = {
        "wechat_appid": _configured(settings.WECHAT_APPID),
        "wechat_secret": _configured(settings.WECHAT_SECRET),
        "session_secret": _configured(settings.SESSION_SECRET) and len(settings.SESSION_SECRET) >= 24,
        "admin_api_token": _configured(settings.ADMIN_API_TOKEN) and len(settings.ADMIN_API_TOKEN) >= 24,
        "auth_dev_mode_off": settings.AUTH_DEV_MODE is False,
        "jobs_available": job_count > 0,
    }
    optional = {
        "llm_real_mode": settings.LLM_STUB_MODE is False and _configured(settings.DEEPSEEK_API_KEY),
        "mailer_real_mode": settings.MAILER_DRY_RUN is False
        and all(_configured(v) for v in (settings.SMTP_HOST, settings.SMTP_USER, settings.SMTP_PASSWORD, settings.SMTP_FROM)),
        "cos_configured": all(
            _configured(v)
            for v in (settings.COS_REGION, settings.COS_BUCKET, settings.COS_SECRET_ID, settings.COS_SECRET_KEY)
        ),
    }

    return {
        "status": "ok" if all(required.values()) else "needs_config",
        "required": required,
        "optional": optional,
        "counts": {
            "jobs": job_count,
            "active_rules": active_rule_count,
        },
        "latest_job_at": latest_job_at.isoformat() if latest_job_at else None,
        "backup": _backup_status(),
    }
