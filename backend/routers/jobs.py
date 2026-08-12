"""岗位浏览接口（已实现）。"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, or_, select
from sqlalchemy.orm import Session

from database import get_db
from models import Job
from schemas import JobOut, JobDetailOut
from services import taxonomy

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=list[JobOut])
def list_jobs(
    db: Session = Depends(get_db),
    district: str | None = None,
    stage: str | None = None,
    subject: str | None = None,
    is_establishment: bool | None = None,
    include_expired: bool = Query(False),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
):
    q = select(Job)
    today = date.today()
    if district:
        q = q.where(Job.district == district)
    if stage:
        q = q.where(Job.stage == stage)
    if subject:
        # 一个公告可能同时招多个学科，所以主要匹配 subjects（竖线包裹的串）。
        # 同时兼容两种历史数据：
        # - subjects 尚未回填的老行 → 回退到单值 subject
        # - 单值里存着旧写法（"心理"而非"心理健康"）→ 别名一并匹配
        canon = taxonomy.normalize_subject(subject) or subject
        aliases = [raw for raw, c in taxonomy.SUBJECT_ALIASES.items() if c == canon]
        q = q.where(
            or_(
                Job.subjects.like(taxonomy.like_pattern(canon)),
                Job.subject.in_([canon, *aliases]),
            )
        )
    if is_establishment is not None:
        q = q.where(Job.is_establishment == is_establishment)
    if not include_expired:
        q = q.where((Job.deadline.is_(None)) | (Job.deadline >= today))
    expiry_rank = case(
        (Job.deadline.is_(None), 1),
        (Job.deadline < today, 2),
        else_=0,
    )
    q = (
        q.order_by(
            expiry_rank.asc(),
            # 不写 NULLS LAST：MySQL 不支持该语法，且 expiry_rank 已把
            # deadline 为空的行单独归到 rank 1，二级排序里不会与非空行混排。
            Job.deadline.asc(),
            Job.crawled_at.desc(),
        )
        .offset((page - 1) * size)
        .limit(size)
    )
    return db.scalars(q).all()


@router.get("/{job_id}", response_model=JobDetailOut)
def get_job(job_id: str, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "岗位不存在")
    return job
