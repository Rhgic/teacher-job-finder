from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from models import ApplicationStatus, EmailApplicationStatus, MatchStatus


T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    total: int
    page: int
    page_size: int
    items: list[T]


class ErrorResponse(BaseModel):
    detail: str


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    openid: str
    nickname: str | None = None
    phone: str | None = None
    created_at: datetime
    updated_at: datetime


class ProfileBase(BaseModel):
    real_name: str | None = None
    email: str | None = None
    target_districts: list[str] = Field(default_factory=list)
    target_stages: list[str] = Field(default_factory=list)
    target_subjects: list[str] = Field(default_factory=list)
    expected_salary_min: int | None = Field(default=None, ge=0)
    expected_salary_max: int | None = Field(default=None, ge=0)
    intro: str | None = None


class ProfileUpsert(ProfileBase):
    user_openid: str = "demo-openid"


class ProfileRead(ProfileBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    created_at: datetime
    updated_at: datetime


class ResumeCreate(BaseModel):
    user_openid: str = "demo-openid"
    name: str
    file_url: str
    summary: str | None = None
    is_default: bool = False


class ResumeUpdate(BaseModel):
    name: str | None = None
    file_url: str | None = None
    summary: str | None = None
    is_default: bool | None = None


class ResumeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    name: str
    file_url: str
    summary: str | None = None
    is_default: bool
    created_at: datetime
    updated_at: datetime


class TemplateCreate(BaseModel):
    user_openid: str = "demo-openid"
    name: str
    subject: str
    body: str
    is_default: bool = False


class TemplateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    name: str
    subject: str
    body: str
    is_default: bool
    created_at: datetime
    updated_at: datetime


class RuleBase(BaseModel):
    name: str
    districts: list[str] = Field(default_factory=list)
    stages: list[str] = Field(default_factory=list)
    subjects: list[str] = Field(default_factory=list)
    salary_min: int | None = Field(default=None, ge=0)
    salary_max: int | None = Field(default=None, ge=0)
    require_bianzhi: bool = False
    active: bool = True
    threshold: int = Field(default=75, ge=0, le=100)


class RuleCreate(RuleBase):
    user_openid: str = "demo-openid"


class RuleUpdate(BaseModel):
    name: str | None = None
    districts: list[str] | None = None
    stages: list[str] | None = None
    subjects: list[str] | None = None
    salary_min: int | None = Field(default=None, ge=0)
    salary_max: int | None = Field(default=None, ge=0)
    require_bianzhi: bool | None = None
    active: bool | None = None
    threshold: int | None = Field(default=None, ge=0, le=100)


class RuleRead(RuleBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    created_at: datetime
    updated_at: datetime


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source: str
    external_id: str
    content_hash: str
    title: str
    school_name: str
    district: str
    stage: str
    subject: str
    headcount: int | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    has_bianzhi: bool
    jd: str
    apply_email: str | None = None
    source_url: str | None = None
    published_at: datetime | None = None
    deadline_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class MatchResultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    rule_id: str
    job_id: str
    user_id: str
    llm_score: int
    matched_points: list[str]
    gaps: list[str]
    reason: str
    cover_letter: str
    status: MatchStatus
    created_at: datetime
    updated_at: datetime


class ApplicationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    job_id: str
    resume_id: str
    template_id: str | None = None
    resume_url_snapshot: str
    email_to: str
    subject: str
    body: str
    status: ApplicationStatus
    error_msg: str | None = None
    sent_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class EmailPreviewCreate(BaseModel):
    job_id: str


class EmailApplicationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    job_id: str
    to_email: str
    subject: str
    body: str
    attachment_path: str | None = None
    status: EmailApplicationStatus
    confirmed_at: datetime | None = None
    sent_at: datetime | None = None
    error_msg: str | None = None
    created_at: datetime
    updated_at: datetime


class EmailPreviewRead(EmailApplicationRead):
    attachment_name: str | None = None
    warning: str = "请确认收件人和内容无误，邮件发出不可撤回。"


class RagAskRequest(BaseModel):
    question: str = Field(..., min_length=1)
    top_k: int = Field(default=3, ge=1, le=10)
    context_title: str | None = Field(default=None, max_length=200)


class RagSourceRead(BaseModel):
    source_id: str
    title: str
    snippet: str
    score: float


class RagAskResponse(BaseModel):
    answer: str
    found: bool
    sources: list[RagSourceRead] = Field(default_factory=list)
