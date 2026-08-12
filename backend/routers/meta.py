"""Meta/operations endpoints that expose non-sensitive readiness state."""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy import func, or_, select, true as sa_true
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from models import Job, SubRule
from services import taxonomy

router = APIRouter(tags=["meta"])


@router.get("/taxonomy")
def get_taxonomy():
    """岗位分类标准表，供前端渲染订阅规则的可选项。

    刻意不按库中已有数据裁剪：订阅规则匹配的是将来爬到的岗位，
    当前没有体育岗位不代表体育老师不能表达求职意向。
    """
    return {
        "subjects": list(taxonomy.SUBJECTS),
        "stages": list(taxonomy.STAGES),
        "districts": list(taxonomy.DISTRICTS),
        "school_types": list(taxonomy.SCHOOL_TYPES),
    }


@router.get("/taxonomy/facets")
def get_taxonomy_facets(
    include_expired: bool = False,
    db: Session = Depends(get_db),
):
    """标准表 + 每个取值下的真实岗位数，供岗位页渲染筛选器。

    为什么不让前端把选项写死：写死过一次，代价是**库里 7 个体育岗位、
    3 个历史岗位在界面上根本点不到**——数据和接口都是好的，只是没人
    给它们做按钮。2026-08-12 实测 105 个岗位里有 41 个属于被漏掉的学科。

    与 /taxonomy 的分工：
    - /taxonomy 给订阅规则用，返回完整标准表（将来会爬到的岗位也要能表达意向）。
    - 这里给岗位浏览用，多带一个 count，让前端把 0 结果的选项置灰。
      置灰而不是隐藏：用户需要知道"这个学科现在没有岗位"，
      而不是以为这个平台压根不收这类岗位。
    """
    # 未过期条件与 /jobs 的默认筛选保持一致，否则计数会和列表对不上：
    # 用户看到"体育 7"点进去却只有 3 条，比不显示数字更糟。
    scope = sa_true() if include_expired else or_(
        Job.deadline.is_(None), Job.deadline >= date.today()
    )

    def counts_for(column):
        rows = db.execute(
            select(column, func.count(Job.id)).where(scope).group_by(column)
        ).all()
        return {k: n for k, n in rows if k}

    # 库里存的可能是旧写法（"心理"），标准表已改叫"心理健康"。
    # 在展示层归一化合并，而不是去改历史数据——同一个学科不该出现两个 chip。
    subject_counts: dict[str, int] = {}
    for raw, n in counts_for(Job.subject).items():
        key = taxonomy.normalize_subject(raw) or raw
        subject_counts[key] = subject_counts.get(key, 0) + n
    stage_counts = counts_for(Job.stage)
    district_counts = counts_for(Job.district)

    def merge(names, counts):
        # 标准表里的顺序优先；库里出现了标准表没有的值也一并列出，
        # 否则那些岗位同样会变成点不到的孤儿。
        known = [{"value": n, "count": counts.get(n, 0)} for n in names]
        extra = [{"value": k, "count": v} for k, v in sorted(counts.items())
                 if k not in set(names)]
        return known + extra

    total = db.scalar(select(func.count(Job.id)).where(scope))
    return {
        "subjects": merge(taxonomy.SUBJECTS, subject_counts),
        "stages": merge(taxonomy.STAGES, stage_counts),
        "districts": merge(taxonomy.DISTRICTS, district_counts),
        "total": total,
        # 学科未识别的岗位数。单列出来是因为它是爬虫质量问题，
        # 不是"没有这类岗位"——藏起来就没人会去修。
        "unclassified_subject": db.scalar(
            select(func.count(Job.id)).where(Job.subject.is_(None), scope)
        ),
    }


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
