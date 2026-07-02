from __future__ import annotations

from pathlib import PurePosixPath

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import EmailApplication, Job, Resume, Template, User, UserProfile


def pick_default_resume(db: Session, user: User) -> Resume | None:
    return db.scalar(
        select(Resume)
        .where(Resume.user_id == user.id)
        .order_by(Resume.is_default.desc(), Resume.created_at.desc())
    )


def pick_default_template(db: Session, user: User) -> Template | None:
    return db.scalar(
        select(Template)
        .where(Template.user_id == user.id)
        .order_by(Template.is_default.desc(), Template.created_at.desc())
    )


def render_subject(job: Job, template: Template | None) -> str:
    if template:
        return template.subject.format(
            school_name=job.school_name,
            subject=job.subject,
            stage=job.stage,
            title=job.title,
        )
    return f"应聘{job.school_name}{job.subject}教师岗位"


def render_body(
    job: Job,
    profile: UserProfile | None,
    resume: Resume | None,
    template: Template | None,
) -> str:
    if template:
        base = template.body.format(
            school_name=job.school_name,
            subject=job.subject,
            stage=job.stage,
            title=job.title,
        )
    else:
        base = (
            f"尊敬的{job.school_name}招聘负责人：您好！\n\n"
            f"我希望应聘贵校{job.subject}教师岗位。"
            "我会结合个人教学经历、班级管理能力与岗位要求，认真完成课堂教学、学生培养和校园活动组织工作。\n\n"
            "期待获得进一步沟通机会，谢谢！"
        )

    facts: list[str] = []
    if profile and profile.real_name:
        facts.append(f"姓名：{profile.real_name}")
    if profile and profile.email:
        facts.append(f"联系邮箱：{profile.email}")
    if resume and resume.summary:
        facts.append(f"简历摘要：{resume.summary}")

    if not facts:
        return base
    return f"{base}\n\n补充信息（来自已填写资料）：\n" + "\n".join(facts)


def attachment_name(attachment_path: str | None) -> str | None:
    if not attachment_path:
        return None
    return PurePosixPath(attachment_path).name or attachment_path


def create_email_preview(db: Session, job: Job, user: User) -> EmailApplication:
    if not job.apply_email:
        raise ValueError("该岗位没有投递邮箱，请先从公告原文补充 apply_email。")

    resume = pick_default_resume(db, user)
    template = pick_default_template(db, user)
    application = EmailApplication(
        job_id=job.id,
        to_email=job.apply_email,
        subject=render_subject(job, template),
        body=render_body(job, user.profile, resume, template),
        attachment_path=resume.file_url if resume else None,
    )
    db.add(application)
    db.commit()
    db.refresh(application)
    return application
