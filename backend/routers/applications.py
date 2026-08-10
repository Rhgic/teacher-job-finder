"""投递接口。所有发送都要用户确认（单条或批量），不做全自动投递。"""
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from deps import get_current_user, require_registered_user
from models import (
    User, Job, MatchResult, Application, ApplicationStatus, MatchStatus,
    Resume, ResumeVersion,
)
from schemas import ApplicationCreate, ApplicationStatusUpdate, BatchConfirm, ApplicationOut
from services import mailer

router = APIRouter(prefix="/applications", tags=["applications"])


def _resolve_attachment(db: Session, user_id: str,
                        resume_id: str | None, resume_version_id: str | None) -> tuple[str | None, str | None]:
    """返回 (附件URL, resume_url_snapshot)。优先用改写版本，其次默认简历。"""
    if resume_version_id:
        rv = db.get(ResumeVersion, resume_version_id)
        if rv and rv.user_id == user_id and rv.file_url:
            return rv.file_url, rv.file_url
    if resume_id:
        r = db.get(Resume, resume_id)
        if r and r.user_id == user_id:
            return r.file_url, r.file_url
    # 兜底：默认简历
    resumes = [r for r in db.get(User, user_id).resumes]
    base = next((r for r in resumes if r.is_default), resumes[0] if resumes else None)
    return (base.file_url if base else None, base.file_url if base else None)


def _send_one(db: Session, user: User, job: Job, body) -> Application:
    if job.deadline and job.deadline < date.today():
        raise HTTPException(400, f"岗位 {job.school_name} 已过截止日期，不能确认投递")
    if not job.recruiter_email:
        raise HTTPException(400, f"岗位 {job.school_name} 缺少招聘方邮箱")
    attach, snapshot = _resolve_attachment(
        db, user.id, getattr(body, "resume_id", None), getattr(body, "resume_version_id", None)
    )
    app = Application(
        user_id=user.id, job_id=job.id,
        match_id=getattr(body, "match_id", None),
        resume_id=getattr(body, "resume_id", None),
        resume_version_id=getattr(body, "resume_version_id", None),
        template_id=getattr(body, "template_id", None),
        recipient_email=job.recruiter_email,
        email_subject=getattr(body, "email_subject", None) or f"应聘{job.school_name}教师岗位",
        resume_url_snapshot=snapshot,
        status=ApplicationStatus.PENDING,
    )
    db.add(app)
    db.flush()

    result = mailer.send_resume(app.recipient_email, app.email_subject or "", "", attach)
    if result["ok"]:
        app.status = ApplicationStatus.SENT
        # 存朴素 UTC，与 models.py 里其余 server_default=func.now() 的时间列保持一致
        app.sent_at = datetime.now(timezone.utc).replace(tzinfo=None)
    else:
        app.status = ApplicationStatus.FAILED
        app.error_msg = result.get("error")
    return app


@router.post("", response_model=ApplicationOut)
def create_application(
    body: ApplicationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_registered_user),
):
    """单条确认投递。"""
    job = db.get(Job, body.job_id)
    if job is None:
        raise HTTPException(404, "岗位不存在")
    app = _send_one(db, user, job, body)
    if body.match_id:
        m = db.get(MatchResult, body.match_id)
        if m:
            m.status = MatchStatus.CONFIRMED
    db.commit()
    db.refresh(app)
    return app


@router.post("/batch-confirm", response_model=list[ApplicationOut])
def batch_confirm(
    body: BatchConfirm,
    db: Session = Depends(get_db),
    user: User = Depends(require_registered_user),
):
    """批量确认投递：高效但仍是用户主动确认这一批，不是全自动。"""
    apps = []
    for match_id in body.match_ids:
        m = db.get(MatchResult, match_id)
        if m is None or m.user_id != user.id:
            continue
        job = db.get(Job, m.job_id)
        if job is None:
            continue
        body_like = ApplicationCreate(
            job_id=job.id, match_id=m.id,
            resume_id=body.resume_id, template_id=body.template_id,
        )
        apps.append(_send_one(db, user, job, body_like))
        m.status = MatchStatus.CONFIRMED
    db.commit()
    for a in apps:
        db.refresh(a)
    return apps


@router.get("", response_model=list[ApplicationOut])
def list_applications(user: User = Depends(get_current_user)):
    return user.applications


@router.patch("/{application_id}/status", response_model=ApplicationOut)
def update_application_status(
    application_id: str,
    body: ApplicationStatusUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_registered_user),
):
    """人工更新投递状态。只改记录，不触发任何自动投递。"""
    app = db.get(Application, application_id)
    if app is None or app.user_id != user.id:
        raise HTTPException(404, "投递记录不存在")
    try:
        app.status = ApplicationStatus(body.status)
    except ValueError as exc:
        allowed = ", ".join(item.value for item in ApplicationStatus)
        raise HTTPException(400, f"状态不支持，可选：{allowed}") from exc
    db.commit()
    db.refresh(app)
    return app
