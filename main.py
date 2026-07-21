from pathlib import Path
from os import getenv
from typing import Annotated, Any

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy import Select, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from config import settings
from database import Base, engine, get_db
from models import ApplicationStatus, DocChunk, EmailApplication, Job, Resume, SubRule, Template, User, UserProfile
from models import MatchResult
from schemas import (
    EmailPreviewCreate,
    EmailPreviewRead,
    ErrorResponse,
    JobRead,
    MatchResultRead,
    Page,
    ProfileRead,
    ProfileUpsert,
    RagAskRequest,
    RagAskResponse,
    ResumeCreate,
    ResumeRead,
    ResumeUpdate,
    RuleCreate,
    RuleRead,
    RuleUpdate,
    TemplateCreate,
    TemplateRead,
)
from services.email_delivery import attachment_name, create_email_preview
from services.pipeline import run_pipeline
from services.llm_match import is_deepseek_configured
from services import rag_index, rag_qa
from services.resume_parser import summarize_resume_file


app = FastAPI(
    title="教师求职小程序 API",
    version="0.1.0",
    description="深圳地区教师求职小程序阶段 1 API：岗位、用户配置、简历、模板与订阅规则 CRUD。",
)

ROOT_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = ROOT_DIR / "uploads" / "resumes"


DbSession = Annotated[Session, Depends(get_db)]


class AuthLoginRequest(BaseModel):
    code: str | None = None


class SettingUpsert(BaseModel):
    value: Any = None


class ApplicationCreate(BaseModel):
    job_id: str


class ApplicationStatusUpdate(BaseModel):
    status: ApplicationStatus


DEMO_SETTINGS: dict[str, Any] = {
    "favorite_jobs": [],
    "saved_searches": [],
    "local_applications": [],
    "materials_checklist": [],
    "notification_preferences": {
        "deadline": True,
        "application": True,
        "materials": True,
        "daily": False,
        "days_before": 3,
        "quiet_start": "22:00",
        "quiet_end": "08:00",
    },
}


@app.on_event("startup")
def ensure_tables() -> None:
    Base.metadata.create_all(bind=engine)


@app.exception_handler(IntegrityError)
async def integrity_error_handler(_: Request, exc: IntegrityError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={"detail": f"数据唯一性冲突或外键约束失败: {exc.orig}"},
    )


@app.exception_handler(ValueError)
async def value_error_handler(_: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"detail": str(exc)},
    )


def get_or_create_user(db: Session, openid: str = "demo-openid") -> User:
    user = db.scalar(select(User).where(User.openid == openid))
    if user:
        return user
    user = User(openid=openid)
    db.add(user)
    db.flush()
    return user


def get_by_id_or_404(db: Session, model: type, item_id: str):
    item = db.get(model, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="资源不存在")
    return item


def paginate(db: Session, stmt: Select, page: int, page_size: int):
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(
        stmt.offset((page - 1) * page_size).limit(page_size)
    ).all()
    return total, items


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def job_to_demo_dict(job: Job) -> dict[str, Any]:
    return {
        "id": job.id,
        "source": job.source,
        "external_id": job.external_id,
        "content_hash": job.content_hash,
        "title": job.title,
        "school_name": job.school_name,
        "district": job.district,
        "stage": job.stage,
        "subject": job.subject,
        "headcount": job.headcount,
        "salary_min": job.salary_min,
        "salary_max": job.salary_max,
        "has_bianzhi": job.has_bianzhi,
        "is_establishment": job.has_bianzhi,
        "jd": job.jd,
        "description": job.jd,
        "apply_email": job.apply_email,
        "recruiter_email": job.apply_email,
        "source_url": job.source_url,
        "published_at": _iso(job.published_at),
        "deadline_at": _iso(job.deadline_at),
        "deadline": _iso(job.deadline_at),
        "created_at": _iso(job.created_at),
        "updated_at": _iso(job.updated_at),
    }


def match_to_demo_dict(match: MatchResult) -> dict[str, Any]:
    return {
        "id": match.id,
        "rule_id": match.rule_id,
        "job_id": match.job_id,
        "user_id": match.user_id,
        "llm_score": match.llm_score,
        "match_reason": match.reason,
        "reason": match.reason,
        "matched_points": match.matched_points,
        "gaps": match.gaps,
        "cover_letter": match.cover_letter,
        "status": match.status,
        "created_at": _iso(match.created_at),
        "updated_at": _iso(match.updated_at),
        "job": job_to_demo_dict(match.job),
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readiness")
def readiness(db: DbSession) -> dict:
    jobs_count = db.scalar(select(func.count()).select_from(Job)) or 0
    active_rules_count = (
        db.scalar(select(func.count()).select_from(SubRule).where(SubRule.active.is_(True))) or 0
    )
    latest_job_at = db.scalar(select(func.max(Job.created_at)))

    required = {
        "wechat_appid": True,
        "wechat_secret": False,
        "session_secret": True,
        "admin_api_token": True,
        "auth_dev_mode_off": False,
        "jobs_available": jobs_count > 0,
    }
    optional = {
        "llm_real_mode": is_deepseek_configured(),
        "email_stub_mode": getenv("EMAIL_STUB_MODE", "1") == "1",
        "mailer_real_mode": getenv("EMAIL_STUB_MODE", "1") != "1",
        "smtp_configured": bool(getenv("SMTP_HOST") and getenv("SMTP_USER") and getenv("SMTP_AUTH_CODE")),
        "cos_configured": False,
    }
    return {
        "status": "ok" if all(required.values()) else "needs_config",
        "required": required,
        "optional": optional,
        "counts": {"jobs": jobs_count, "active_rules": active_rules_count},
        "latest_job_at": latest_job_at.isoformat() if latest_job_at else None,
        "backup": {
            "ok": False,
            "count": 0,
            "latest_at": None,
            "latest_size_bytes": 0,
            "latest_file": None,
        },
    }


@app.get("/")
def root() -> FileResponse:
    return FileResponse(ROOT_DIR / "index.html")


@app.get("/app")
def browser_app() -> FileResponse:
    return FileResponse(ROOT_DIR / "index.html")


@app.get("/api-info")
def api_info() -> dict[str, str]:
    return {
        "name": "教师求职小程序 API",
        "docs": "/docs",
        "health": "/health",
        "jobs": "/jobs",
        "wechat_miniprogram": "./miniprogram",
    }


@app.post("/auth/login")
def login_for_local_demo(payload: AuthLoginRequest, db: DbSession) -> dict[str, str]:
    """Local demo login: returns a stable demo user instead of calling WeChat servers."""
    user = get_or_create_user(db, "demo-openid")
    return {
        "token": f"demo-token-{payload.code or 'local'}",
        "user_id": user.id,
        "openid": user.openid,
    }


@app.get(
    "/jobs",
    response_model=Page[JobRead],
    responses={400: {"model": ErrorResponse}},
)
def list_jobs(
    db: DbSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    district: str | None = None,
    stage: str | None = None,
    subject: str | None = None,
) -> Page[JobRead]:
    stmt = select(Job).order_by(Job.published_at.desc().nullslast(), Job.created_at.desc())
    if district:
        stmt = stmt.where(Job.district == district)
    if stage:
        stmt = stmt.where(Job.stage == stage)
    if subject:
        stmt = stmt.where(Job.subject == subject)
    total, items = paginate(db, stmt, page, page_size)
    return Page[JobRead](total=total, page=page, page_size=page_size, items=items)


@app.get("/jobs/{job_id}", response_model=JobRead)
def get_job(job_id: str, db: DbSession) -> Job:
    return get_by_id_or_404(db, Job, job_id)


@app.get("/profile", response_model=ProfileRead)
def get_profile(db: DbSession, user_openid: str = "demo-openid") -> UserProfile:
    user = get_or_create_user(db, user_openid)
    if not user.profile:
        profile = UserProfile(user_id=user.id)
        db.add(profile)
        db.commit()
        db.refresh(profile)
        return profile
    return user.profile


@app.put("/profile", response_model=ProfileRead)
def upsert_profile(payload: ProfileUpsert, db: DbSession) -> UserProfile:
    user = get_or_create_user(db, payload.user_openid)
    profile = user.profile or UserProfile(user_id=user.id)
    for field, value in payload.model_dump(exclude={"user_openid"}).items():
        setattr(profile, field, value)
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


@app.get("/resumes", response_model=list[ResumeRead])
def list_resumes(db: DbSession, user_openid: str = "demo-openid") -> list[Resume]:
    user = get_or_create_user(db, user_openid)
    return db.scalars(
        select(Resume).where(Resume.user_id == user.id).order_by(Resume.created_at.desc())
    ).all()


@app.post("/resumes", response_model=ResumeRead, status_code=status.HTTP_201_CREATED)
def create_resume(payload: ResumeCreate, db: DbSession) -> Resume:
    user = get_or_create_user(db, payload.user_openid)
    resume = Resume(**payload.model_dump(exclude={"user_openid"}), user_id=user.id)
    if resume.is_default:
        db.query(Resume).filter(Resume.user_id == user.id).update({"is_default": False})
    db.add(resume)
    db.commit()
    db.refresh(resume)
    return resume


@app.post("/resumes/upload", response_model=ResumeRead, status_code=status.HTTP_201_CREATED)
async def upload_resume(
    db: DbSession,
    file: UploadFile = File(...),
    name: str | None = Form(default=None),
    user_openid: str = Form(default="demo-openid"),
    is_default: bool = Form(default=True),
) -> Resume:
    raw_name = Path(file.filename or "resume").name
    suffix = Path(raw_name).suffix.lower()
    if suffix not in {".pdf", ".txt", ".md", ".doc", ".docx"}:
        raise HTTPException(status_code=400, detail="只支持 PDF、Word、TXT、Markdown 简历文件")

    user = get_or_create_user(db, user_openid)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    stored_name = f"{user.id}_{__import__('uuid').uuid4().hex}{suffix}"
    path = UPLOAD_DIR / stored_name
    content = await file.read()
    if len(content) > 8 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="演示环境单个简历文件不能超过 8MB")
    path.write_bytes(content)

    summary, parse_note = summarize_resume_file(path)
    resume = Resume(
        user_id=user.id,
        name=name or Path(raw_name).stem or "上传简历",
        file_url=f"local://uploads/resumes/{stored_name}",
        summary=summary or parse_note,
        is_default=is_default,
    )
    if resume.is_default:
        db.query(Resume).filter(Resume.user_id == user.id).update({"is_default": False})
    db.add(resume)
    db.commit()
    db.refresh(resume)
    return resume


@app.put("/resumes/{resume_id}", response_model=ResumeRead)
def update_resume(resume_id: str, payload: ResumeUpdate, db: DbSession) -> Resume:
    resume = get_by_id_or_404(db, Resume, resume_id)
    data = payload.model_dump(exclude_unset=True)
    if data.get("is_default"):
        db.query(Resume).filter(Resume.user_id == resume.user_id, Resume.id != resume.id).update(
            {"is_default": False}
        )
    for field, value in data.items():
        setattr(resume, field, value)
    db.add(resume)
    db.commit()
    db.refresh(resume)
    return resume


@app.delete("/resumes/{resume_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_resume(resume_id: str, db: DbSession) -> None:
    resume = get_by_id_or_404(db, Resume, resume_id)
    db.delete(resume)
    db.commit()


@app.get("/templates", response_model=list[TemplateRead])
def list_templates(db: DbSession, user_openid: str = "demo-openid") -> list[Template]:
    user = get_or_create_user(db, user_openid)
    return db.scalars(
        select(Template).where(Template.user_id == user.id).order_by(Template.created_at.desc())
    ).all()


@app.post("/templates", response_model=TemplateRead, status_code=status.HTTP_201_CREATED)
def create_template(payload: TemplateCreate, db: DbSession) -> Template:
    user = get_or_create_user(db, payload.user_openid)
    template = Template(**payload.model_dump(exclude={"user_openid"}), user_id=user.id)
    if template.is_default:
        db.query(Template).filter(Template.user_id == user.id).update({"is_default": False})
    db.add(template)
    db.commit()
    db.refresh(template)
    return template


@app.delete("/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template(template_id: str, db: DbSession) -> None:
    template = get_by_id_or_404(db, Template, template_id)
    db.delete(template)
    db.commit()


@app.get("/rules", response_model=list[RuleRead])
def list_rules(db: DbSession, user_openid: str = "demo-openid") -> list[SubRule]:
    user = get_or_create_user(db, user_openid)
    return db.scalars(
        select(SubRule).where(SubRule.user_id == user.id).order_by(SubRule.created_at.desc())
    ).all()


@app.post("/rules", response_model=RuleRead, status_code=status.HTTP_201_CREATED)
def create_rule(payload: RuleCreate, db: DbSession) -> SubRule:
    user = get_or_create_user(db, payload.user_openid)
    rule = SubRule(**payload.model_dump(exclude={"user_openid"}), user_id=user.id)
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


@app.put("/rules/{rule_id}", response_model=RuleRead)
def update_rule(rule_id: str, payload: RuleUpdate, db: DbSession) -> SubRule:
    rule = get_by_id_or_404(db, SubRule, rule_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(rule, field, value)
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


@app.delete("/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rule(rule_id: str, db: DbSession) -> None:
    rule = get_by_id_or_404(db, SubRule, rule_id)
    db.delete(rule)
    db.commit()


@app.post("/pipeline/run")
def run_matching_pipeline(db: DbSession, user_openid: str | None = "demo-openid") -> dict[str, int]:
    return run_pipeline(db, user_openid=user_openid)


@app.get("/matches", response_model=list[MatchResultRead])
def list_matches(db: DbSession, user_openid: str = "demo-openid") -> list[MatchResult]:
    user = get_or_create_user(db, user_openid)
    return db.scalars(
        select(MatchResult)
        .where(MatchResult.user_id == user.id)
        .order_by(MatchResult.llm_score.desc(), MatchResult.created_at.desc())
    ).all()


@app.get("/recommendations")
def list_recommendations(db: DbSession, user_openid: str = "demo-openid") -> list[dict[str, Any]]:
    user = get_or_create_user(db, user_openid)
    matches = db.scalars(
        select(MatchResult)
        .where(MatchResult.user_id == user.id)
        .order_by(MatchResult.llm_score.desc(), MatchResult.created_at.desc())
    ).all()
    if not matches:
        run_pipeline(db, user_openid=user_openid)
        matches = db.scalars(
            select(MatchResult)
            .where(MatchResult.user_id == user.id)
            .order_by(MatchResult.llm_score.desc(), MatchResult.created_at.desc())
        ).all()
    return [match_to_demo_dict(match) for match in matches]


@app.get("/settings/{key}")
def get_setting(key: str) -> dict[str, Any]:
    return {"key": key, "value": DEMO_SETTINGS.get(key)}


@app.put("/settings/{key}")
def put_setting(key: str, payload: SettingUpsert) -> dict[str, Any]:
    DEMO_SETTINGS[key] = payload.value
    return {"key": key, "value": payload.value}


@app.get("/applications")
def list_applications() -> list[dict[str, Any]]:
    """The miniprogram keeps demo follow-up records in /settings/local_applications."""
    return []


@app.post("/applications", status_code=status.HTTP_201_CREATED)
def create_application_for_local_demo(payload: ApplicationCreate, db: DbSession) -> dict[str, Any]:
    job = get_by_id_or_404(db, Job, payload.job_id)
    if job.deadline_at and job.deadline_at.date() < __import__("datetime").date.today():
        raise HTTPException(status_code=400, detail="该岗位已过截止日期，演示环境不会确认投递。")
    return {
        "id": f"demo-application-{job.id}",
        "job_id": job.id,
        "job_title": job.title,
        "school_name": job.school_name,
        "recipient_email": job.apply_email,
        "status": "pending",
        "sent_at": None,
    }


@app.patch("/applications/{application_id}/status")
def update_application_status_for_local_demo(
    application_id: str,
    payload: ApplicationStatusUpdate,
) -> dict[str, Any]:
    return {"id": application_id, "status": payload.status}


@app.post("/crawl/run")
def run_crawl_for_local_demo() -> dict[str, Any]:
    return {
        "status": "skipped",
        "message": "本地演示版不触发真实抓取，岗位数据来自 seed.py。",
    }


@app.post("/email/preview", response_model=EmailPreviewRead, status_code=status.HTTP_201_CREATED)
def preview_email_application(
    payload: EmailPreviewCreate,
    db: DbSession,
    user_openid: str = "demo-openid",
) -> EmailPreviewRead:
    user = get_or_create_user(db, user_openid)
    job = get_by_id_or_404(db, Job, payload.job_id)
    application: EmailApplication = create_email_preview(db, job, user)
    return EmailPreviewRead(
        id=application.id,
        job_id=application.job_id,
        to_email=application.to_email,
        subject=application.subject,
        body=application.body,
        attachment_path=application.attachment_path,
        attachment_name=attachment_name(application.attachment_path),
        status=application.status,
        confirmed_at=application.confirmed_at,
        sent_at=application.sent_at,
        error_msg=application.error_msg,
        created_at=application.created_at,
        updated_at=application.updated_at,
    )


@app.post("/rag/reindex")
def reindex_rag(db: DbSession) -> dict[str, int]:
    """Rebuild local RAG chunks from job notices. Stub embedding works offline."""
    return rag_index.reindex(db)


@app.get("/rag/status")
def rag_status(db: DbSession) -> dict[str, Any]:
    """Expose the local knowledge-base state for the mini-program UI."""
    jobs = db.scalar(select(func.count()).select_from(Job)) or 0
    chunks = db.scalar(select(func.count()).select_from(DocChunk)) or 0
    return {
        "ready": chunks > 0,
        "jobs": jobs,
        "chunks": chunks,
        "demo_mode": settings.LLM_STUB_MODE or settings.EMBEDDING_STUB_MODE,
    }


@app.post("/rag/ask", response_model=RagAskResponse)
def ask_rag(payload: RagAskRequest, db: DbSession) -> dict:
    """Answer from indexed notice chunks; return found=false when no evidence is found."""
    return rag_qa.ask(
        db,
        payload.question,
        k=payload.top_k,
        context_title=payload.context_title,
    )
