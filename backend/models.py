"""
教师求职小程序 —— 数据模型层 (SQLAlchemy 2.0)

约定:
- 主键统一用 str(uuid4)，String(36) 存储，跨 SQLite/MySQL/PostgreSQL 通用。
- 高频筛选字段 (district/stage/subject 等) 单独建列并加索引；
  多选型配置 (订阅规则的区域/学段等) 用 JSON 存，避免多对多中间表。
- 两条状态机用枚举约束 (MatchStatus / ApplicationStatus)，禁止裸字符串。
- 时间戳统一用数据库 server 默认值。
"""
from __future__ import annotations

import uuid
from datetime import datetime, date
from enum import Enum as PyEnum

from sqlalchemy import (
    String, Integer, Boolean, Text, DateTime, Date, JSON, Enum,
    ForeignKey, UniqueConstraint, func,
)
from sqlalchemy.orm import (
    DeclarativeBase, Mapped, mapped_column, relationship,
)


def gen_uuid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


# --------------------------------------------------------------------------- #
# 枚举：学校性质 + 两条状态机                                                    #
# --------------------------------------------------------------------------- #
class SchoolType(str, PyEnum):
    PUBLIC = "public"    # 公办
    PRIVATE = "private"  # 民办


class MatchStatus(str, PyEnum):
    """匹配结果状态机：待推送 → 已推送 → 已确认 / 已忽略"""
    PENDING_PUSH = "pending_push"
    PUSHED = "pushed"
    CONFIRMED = "confirmed"
    IGNORED = "ignored"


class ApplicationStatus(str, PyEnum):
    """投递状态机：待发送 → 已发送 → 送达 / 失败 / 退信"""
    PENDING = "pending"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"
    BOUNCED = "bounced"


class ResumeVersionStatus(str, PyEnum):
    """简历改写版本状态：草稿 → 审核通过 / 弃用（必须人工审核后才可用于投递）"""
    DRAFT = "draft"
    APPROVED = "approved"
    DISCARDED = "discarded"


# --------------------------------------------------------------------------- #
# 1. 用户账号                                                                   #
# --------------------------------------------------------------------------- #
class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    openid: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # 微信登录
    nickname: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    profile: Mapped["UserProfile"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
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
    applications: Mapped[list["Application"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    settings: Mapped[list["UserSetting"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


# --------------------------------------------------------------------------- #
# 2. 用户配置（求职信息，1:1）                                                   #
# --------------------------------------------------------------------------- #
class UserProfile(Base):
    __tablename__ = "user_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )
    real_name: Mapped[str | None] = mapped_column(String(32))
    phone: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(128))   # 投递时的回信地址
    education: Mapped[str | None] = mapped_column(String(32))  # 学历
    major: Mapped[str | None] = mapped_column(String(64))     # 专业
    subject: Mapped[str | None] = mapped_column(String(32))   # 任教学科
    cert_no: Mapped[str | None] = mapped_column(String(64))   # 教师资格证号
    # 求职意向：{"districts": [...], "stages": [...], "establishment": true}
    intent: Mapped[dict | None] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="profile")


# --------------------------------------------------------------------------- #
# 3. 简历文件                                                                   #
# --------------------------------------------------------------------------- #
class Resume(Base):
    __tablename__ = "resumes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    file_name: Mapped[str] = mapped_column(String(256))
    file_url: Mapped[str] = mapped_column(String(512))   # 对象存储 COS 地址
    file_size: Mapped[int | None] = mapped_column(Integer)
    # 结构化简历内容（自动改写读取/编辑的对象）；上传 PDF 可解析一次填入，或用户手填
    structured_content: Mapped[dict | None] = mapped_column(JSON)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="resumes")


# --------------------------------------------------------------------------- #
# 4. 内容模板（求职信 / 自我介绍）                                               #
# --------------------------------------------------------------------------- #
class Template(Base):
    __tablename__ = "templates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(128))
    content: Mapped[str] = mapped_column(Text)        # 含占位符，如 {school_name}
    type: Mapped[str | None] = mapped_column(String(32))  # cover_letter / self_intro
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="templates")


# --------------------------------------------------------------------------- #
# 5. 岗位（爬虫抓取 / 手动种子）                                                 #
# --------------------------------------------------------------------------- #
class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    source: Mapped[str | None] = mapped_column(String(64))       # 来源站点
    source_url: Mapped[str | None] = mapped_column(String(512))
    external_id: Mapped[str | None] = mapped_column(String(128), index=True)  # 原站唯一ID
    school_name: Mapped[str] = mapped_column(String(128), index=True)
    school_type: Mapped[SchoolType | None] = mapped_column(Enum(SchoolType))
    district: Mapped[str | None] = mapped_column(String(32), index=True)  # 区域
    stage: Mapped[str | None] = mapped_column(String(32), index=True)     # 学段
    subject: Mapped[str | None] = mapped_column(String(32), index=True)   # 学科
    is_establishment: Mapped[bool | None] = mapped_column(Boolean)        # 是否编制
    salary_min: Mapped[int | None] = mapped_column(Integer)
    salary_max: Mapped[int | None] = mapped_column(Integer)
    recruiter_email: Mapped[str | None] = mapped_column(String(128))      # 投递邮箱
    description: Mapped[str | None] = mapped_column(Text)                  # JD 全文
    deadline: Mapped[date | None] = mapped_column(Date)
    content_hash: Mapped[str | None] = mapped_column(String(64), index=True)  # 去重指纹
    crawled_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    matches: Mapped[list["MatchResult"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )

    # (来源, 原站ID) 联合唯一，防止同一岗位重复入库
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_job_source_external"),
    )


# --------------------------------------------------------------------------- #
# 6. 订阅规则（用户的筛选条件，支持多套并行）                                     #
# --------------------------------------------------------------------------- #
class SubRule(Base):
    __tablename__ = "sub_rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(64))          # 规则名，如"南山·小学语文·编制"
    districts: Mapped[list | None] = mapped_column(JSON)    # ["南山区", "福田区"]
    stages: Mapped[list | None] = mapped_column(JSON)       # ["小学"]
    subjects: Mapped[list | None] = mapped_column(JSON)     # ["语文"]
    school_types: Mapped[list | None] = mapped_column(JSON)  # ["public"]
    salary_floor: Mapped[int | None] = mapped_column(Integer)
    need_establishment: Mapped[bool | None] = mapped_column(Boolean)
    llm_threshold: Mapped[int] = mapped_column(Integer, default=70)  # 分数阈值 0-100
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="rules")
    matches: Mapped[list["MatchResult"]] = relationship(
        back_populates="rule", cascade="all, delete-orphan"
    )


# --------------------------------------------------------------------------- #
# 7. 匹配结果（订阅规则 × 岗位 的交叉产出，自动化管道核心）                        #
# --------------------------------------------------------------------------- #
class MatchResult(Base):
    __tablename__ = "match_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    rule_id: Mapped[str] = mapped_column(
        ForeignKey("sub_rules.id", ondelete="CASCADE"), index=True
    )
    job_id: Mapped[str] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(  # 冗余字段，便于直接按用户查询
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    rule_passed: Mapped[bool] = mapped_column(Boolean, default=False)  # 第一层规则是否通过
    llm_score: Mapped[int | None] = mapped_column(Integer)            # 第二层 LLM 评分 0-100
    match_reason: Mapped[str | None] = mapped_column(Text)            # LLM 命中理由
    cover_letter: Mapped[str | None] = mapped_column(Text)           # 生成的求职信草稿
    status: Mapped[MatchStatus] = mapped_column(
        Enum(MatchStatus), default=MatchStatus.PENDING_PUSH
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    rule: Mapped["SubRule"] = relationship(back_populates="matches")
    job: Mapped["Job"] = relationship(back_populates="matches")

    # 一条规则对同一岗位只评一次
    __table_args__ = (
        UniqueConstraint("rule_id", "job_id", name="uq_match_rule_job"),
    )


# --------------------------------------------------------------------------- #
# 8. 投递记录                                                                   #
# --------------------------------------------------------------------------- #
class Application(Base):
    __tablename__ = "applications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    match_id: Mapped[str | None] = mapped_column(ForeignKey("match_results.id"))  # 来源匹配
    resume_id: Mapped[str | None] = mapped_column(ForeignKey("resumes.id"))       # 投了哪份（原件）
    resume_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("resume_versions.id")
    )  # 若用了针对该岗改写的版本
    template_id: Mapped[str | None] = mapped_column(ForeignKey("templates.id"))   # 用了哪个模板
    recipient_email: Mapped[str] = mapped_column(String(128))
    email_subject: Mapped[str | None] = mapped_column(String(256))
    resume_url_snapshot: Mapped[str | None] = mapped_column(String(512))  # 留档：投递当时的简历地址
    status: Mapped[ApplicationStatus] = mapped_column(
        Enum(ApplicationStatus), default=ApplicationStatus.PENDING
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    error_msg: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="applications")


# --------------------------------------------------------------------------- #
# 9. 针对岗位改写的简历版本（自动定制，必须人工审核通过后才可投递）               #
# --------------------------------------------------------------------------- #
class ResumeVersion(Base):
    __tablename__ = "resume_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    base_resume_id: Mapped[str] = mapped_column(  # 基于哪份原始简历改写
        ForeignKey("resumes.id", ondelete="CASCADE"), index=True
    )
    match_id: Mapped[str | None] = mapped_column(ForeignKey("match_results.id"))  # 关联的匹配
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id"))             # 针对哪个岗位
    tailored_content: Mapped[dict | None] = mapped_column(JSON)  # 改写后的结构化简历
    # 改动清单：逐条说明改了什么（供用户核对、防止 LLM 虚构经历）
    change_summary: Mapped[str | None] = mapped_column(Text)
    file_url: Mapped[str | None] = mapped_column(String(512))    # 渲染后的 PDF，审核通过才生成
    status: Mapped[ResumeVersionStatus] = mapped_column(
        Enum(ResumeVersionStatus), default=ResumeVersionStatus.DRAFT
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# --------------------------------------------------------------------------- #
# 10. 用户轻量设置（保存搜索、材料清单等小工具状态）                            #
# --------------------------------------------------------------------------- #
class UserSetting(Base):
    __tablename__ = "user_settings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    key: Mapped[str] = mapped_column(String(64), index=True)
    value: Mapped[dict | list | None] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="settings")

    __table_args__ = (
        UniqueConstraint("user_id", "key", name="uq_user_setting_key"),
    )


# --------------------------------------------------------------------------- #
# 11. RAG 文档切片（招聘公告问答索引）                                          #
# --------------------------------------------------------------------------- #
class DocChunk(Base):
    __tablename__ = "doc_chunks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    source_type: Mapped[str] = mapped_column(String(32), index=True)  # job / 后续可扩展
    source_id: Mapped[str] = mapped_column(String(36), index=True)
    source_title: Mapped[str | None] = mapped_column(String(128))
    content: Mapped[str] = mapped_column(Text)
    chunk_index: Mapped[int] = mapped_column(Integer)
    embedding: Mapped[str] = mapped_column(Text)  # JSON 文本，避免绑定特定向量库
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("source_type", "source_id", "chunk_index", name="uq_doc_chunk_source_idx"),
    )
