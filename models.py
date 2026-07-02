from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


def new_uuid() -> str:
    return str(uuid4())


class MatchStatus(StrEnum):
    pending_push = "pending_push"
    pushed = "pushed"
    confirmed = "confirmed"
    ignored = "ignored"


class ApplicationStatus(StrEnum):
    pending = "pending"
    sent = "sent"
    delivered = "delivered"
    failed = "failed"
    bounced = "bounced"


class EmailApplicationStatus(StrEnum):
    draft = "draft"
    sent = "sent"
    failed = "failed"


MATCH_TRANSITIONS = {
    MatchStatus.pending_push: {MatchStatus.pushed, MatchStatus.confirmed, MatchStatus.ignored},
    MatchStatus.pushed: {MatchStatus.confirmed, MatchStatus.ignored},
    MatchStatus.confirmed: set(),
    MatchStatus.ignored: set(),
}

APPLICATION_TRANSITIONS = {
    ApplicationStatus.pending: {ApplicationStatus.sent, ApplicationStatus.failed},
    ApplicationStatus.sent: {
        ApplicationStatus.delivered,
        ApplicationStatus.failed,
        ApplicationStatus.bounced,
    },
    ApplicationStatus.delivered: set(),
    ApplicationStatus.failed: set(),
    ApplicationStatus.bounced: set(),
}


def transition_match_status(current: MatchStatus, target: MatchStatus) -> MatchStatus:
    if target not in MATCH_TRANSITIONS[current]:
        raise ValueError(f"Invalid match status transition: {current} -> {target}")
    return target


def transition_application_status(
    current: ApplicationStatus, target: ApplicationStatus
) -> ApplicationStatus:
    if target not in APPLICATION_TRANSITIONS[current]:
        raise ValueError(f"Invalid application status transition: {current} -> {target}")
    return target


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    openid: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    nickname: Mapped[str | None] = mapped_column(String(80), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)

    profile: Mapped["UserProfile | None"] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    resumes: Mapped[list["Resume"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    templates: Mapped[list["Template"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    rules: Mapped[list["SubRule"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class UserProfile(Base, TimestampMixin):
    __tablename__ = "user_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    real_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    email: Mapped[str | None] = mapped_column(String(160), nullable=True)
    target_districts: Mapped[list[str]] = mapped_column(JSON, default=list)
    target_stages: Mapped[list[str]] = mapped_column(JSON, default=list)
    target_subjects: Mapped[list[str]] = mapped_column(JSON, default=list)
    expected_salary_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expected_salary_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    intro: Mapped[str | None] = mapped_column(Text, nullable=True)

    user: Mapped[User] = relationship(back_populates="profile")


class Resume(Base, TimestampMixin):
    __tablename__ = "resumes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    file_url: Mapped[str] = mapped_column(String(500))
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_default: Mapped[bool] = mapped_column(default=False)

    user: Mapped[User] = relationship(back_populates="resumes")


class Template(Base, TimestampMixin):
    __tablename__ = "templates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    subject: Mapped[str] = mapped_column(String(180))
    body: Mapped[str] = mapped_column(Text)
    is_default: Mapped[bool] = mapped_column(default=False)

    user: Mapped[User] = relationship(back_populates="templates")


class Job(Base, TimestampMixin):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_jobs_source_external_id"),
        Index("ix_jobs_district_stage_subject", "district", "stage", "subject"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    source: Mapped[str] = mapped_column(String(80))
    external_id: Mapped[str] = mapped_column(String(120))
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(200))
    school_name: Mapped[str] = mapped_column(String(160))
    district: Mapped[str] = mapped_column(String(40), index=True)
    stage: Mapped[str] = mapped_column(String(40), index=True)
    subject: Mapped[str] = mapped_column(String(40), index=True)
    headcount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    has_bianzhi: Mapped[bool] = mapped_column(default=False)
    jd: Mapped[str] = mapped_column(Text)
    apply_email: Mapped[str | None] = mapped_column(String(160), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class SubRule(Base, TimestampMixin):
    __tablename__ = "sub_rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    districts: Mapped[list[str]] = mapped_column(JSON, default=list)
    stages: Mapped[list[str]] = mapped_column(JSON, default=list)
    subjects: Mapped[list[str]] = mapped_column(JSON, default=list)
    salary_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    require_bianzhi: Mapped[bool] = mapped_column(default=False)
    active: Mapped[bool] = mapped_column(default=True)
    threshold: Mapped[int] = mapped_column(Integer, default=75)

    user: Mapped[User] = relationship(back_populates="rules")
    match_results: Mapped[list["MatchResult"]] = relationship(
        back_populates="rule", cascade="all, delete-orphan"
    )


class MatchResult(Base, TimestampMixin):
    __tablename__ = "match_results"
    __table_args__ = (UniqueConstraint("rule_id", "job_id", name="uq_match_rule_job"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    rule_id: Mapped[str] = mapped_column(ForeignKey("sub_rules.id"), index=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    llm_score: Mapped[int] = mapped_column(Integer)
    matched_points: Mapped[list[str]] = mapped_column(JSON, default=list)
    gaps: Mapped[list[str]] = mapped_column(JSON, default=list)
    reason: Mapped[str] = mapped_column(Text)
    cover_letter: Mapped[str] = mapped_column(Text)
    status: Mapped[MatchStatus] = mapped_column(
        Enum(MatchStatus), default=MatchStatus.pending_push
    )

    rule: Mapped[SubRule] = relationship(back_populates="match_results")
    job: Mapped[Job] = relationship()


class Application(Base, TimestampMixin):
    __tablename__ = "applications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    resume_id: Mapped[str] = mapped_column(ForeignKey("resumes.id"))
    template_id: Mapped[str | None] = mapped_column(ForeignKey("templates.id"), nullable=True)
    resume_url_snapshot: Mapped[str] = mapped_column(String(500))
    email_to: Mapped[str] = mapped_column(String(160))
    subject: Mapped[str] = mapped_column(String(180))
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[ApplicationStatus] = mapped_column(
        Enum(ApplicationStatus), default=ApplicationStatus.pending
    )
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class EmailApplication(Base, TimestampMixin):
    __tablename__ = "email_applications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    to_email: Mapped[str] = mapped_column(String(160))
    subject: Mapped[str] = mapped_column(String(180))
    body: Mapped[str] = mapped_column(Text)
    attachment_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[EmailApplicationStatus] = mapped_column(
        Enum(EmailApplicationStatus), default=EmailApplicationStatus.draft, index=True
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)

    job: Mapped[Job] = relationship()


class DocChunk(Base):
    __tablename__ = "doc_chunks"
    __table_args__ = (
        UniqueConstraint("source_type", "source_id", "chunk_index", name="uq_doc_chunk_source_idx"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    source_type: Mapped[str] = mapped_column(String(32), index=True)
    source_id: Mapped[str] = mapped_column(String(36), index=True)
    source_title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    content: Mapped[str] = mapped_column(Text)
    chunk_index: Mapped[int] = mapped_column(Integer)
    embedding: Mapped[str] = mapped_column(Text)

    job: Mapped[Job | None] = relationship(
        primaryjoin="foreign(DocChunk.source_id) == Job.id",
        viewonly=True,
    )
