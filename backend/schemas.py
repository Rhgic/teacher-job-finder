"""Pydantic v2 数据传输对象（与 ORM 模型解耦）。

约定：Out = 响应模型（from ORM）；In = 请求体。
字段保持精简，Codex 可按需扩展。
"""
from __future__ import annotations

from datetime import datetime, date
from pydantic import BaseModel, ConfigDict


class _ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------- 岗位 ----------------
class JobOut(_ORM):
    id: str
    source_url: str | None = None
    school_name: str
    school_type: str | None = None
    district: str | None = None
    stage: str | None = None
    subject: str | None = None
    is_establishment: bool | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    recruiter_email: str | None = None
    deadline: date | None = None


class JobDetailOut(JobOut):
    description: str | None = None


# ---------------- 用户配置 ----------------
class ProfileIn(BaseModel):
    real_name: str | None = None
    phone: str | None = None
    email: str | None = None
    education: str | None = None
    major: str | None = None
    subject: str | None = None
    cert_no: str | None = None
    intent: dict | None = None


class ProfileOut(_ORM, ProfileIn):
    id: str
    updated_at: datetime | None = None


# ---------------- 轻量设置 ----------------
class SettingIn(BaseModel):
    value: dict | list | None = None


class SettingOut(_ORM):
    key: str
    value: dict | list | None = None
    updated_at: datetime | None = None


# ---------------- 简历 ----------------
class ResumeIn(BaseModel):
    file_name: str
    file_url: str
    file_size: int | None = None
    is_default: bool = False
    structured_content: dict | None = None


class ResumeOut(_ORM):
    id: str
    file_name: str
    file_url: str
    is_default: bool
    structured_content: dict | None = None
    uploaded_at: datetime | None = None


# ---------------- 模板 ----------------
class TemplateIn(BaseModel):
    title: str
    content: str
    type: str | None = None


class TemplateOut(_ORM, TemplateIn):
    id: str


# ---------------- 订阅规则 ----------------
class RuleIn(BaseModel):
    name: str
    districts: list[str] | None = None
    stages: list[str] | None = None
    subjects: list[str] | None = None
    school_types: list[str] | None = None
    salary_floor: int | None = None
    need_establishment: bool | None = None
    llm_threshold: int = 70
    is_active: bool = True


class RuleOut(_ORM, RuleIn):
    id: str


# ---------------- 匹配结果 / 推荐 ----------------
class MatchOut(_ORM):
    id: str
    job_id: str
    llm_score: int | None = None
    match_reason: str | None = None
    matched_points: list[str] | None = None
    gaps: list[str] | None = None
    cover_letter: str | None = None
    status: str
    job: JobOut | None = None


# ---------------- 投递 ----------------
class ApplicationCreate(BaseModel):
    job_id: str
    match_id: str | None = None
    resume_id: str | None = None
    resume_version_id: str | None = None
    template_id: str | None = None
    email_subject: str | None = None


class ApplicationStatusUpdate(BaseModel):
    status: str


class BatchConfirm(BaseModel):
    """批量确认投递：传一组 match_id，逐条生成并发送（保留最后一道人工闸）。"""
    match_ids: list[str]
    resume_id: str | None = None
    template_id: str | None = None


class ApplicationOut(_ORM):
    id: str
    job_id: str
    recipient_email: str
    status: str
    sent_at: datetime | None = None
    error_msg: str | None = None
