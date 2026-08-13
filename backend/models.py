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

    # 三种身份来源并存，靠不同列区分，不另设 type 字段：
    # - 微信用户：openid 有值，email 为空（历史用户，保留可登录）
    # - 邮箱用户：email + password_hash 有值，is_guest=False
    # - 访客：openid 为 guest_ 前缀，is_guest=True，不能保存任何个人数据
    # openid 与 email 都放宽为可空，但各自唯一：唯一索引允许多个 NULL，
    # 所以"一批微信用户 email 全为空"不会互相冲突。
    openid: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    # 见 services/auth.py：scrypt$N$r$p$salt_b64$hash_b64，自描述参数便于日后升级
    password_hash: Mapped[str | None] = mapped_column(String(255))
    is_guest: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
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
    model_config_row: Mapped["UserModelConfig | None"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )


# --------------------------------------------------------------------------- #
# 1b. 用户自带模型配置（DeepSeek API Key，1:1）                                  #
# --------------------------------------------------------------------------- #
class UserModelConfig(Base):
    """用户自带的 DeepSeek Key 与模型选择。

    安全约定（改这张表前先读）：
    - `encrypted_key` 是唯一的 Key 载体，Fernet 密文，明文绝不落库。
    - `key_last4` 是明文，但只有 4 个字符，用于前端显示 sk-****abcd。
      规格要求展示掩码，没有它就只能把密文解出来再截断，反而更危险。
    - `key_fingerprint` 是 sha256(明文) 的前 32 位十六进制，用来判断
      "用户这次是不是真的换了 Key"，不必解密即可比较。
    - 这张表的任何字段都不得进日志、不得进任务载荷、不得原样进响应。
    """

    __tablename__ = "user_model_configs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    # 唯一性由 __table_args__ 里的 UniqueConstraint 表达，这里只声明普通索引。
    # 写成 unique=True 会让 SQLAlchemy 把 ix_ 索引本身建成唯一索引，
    # 而迁移 a421 建的是「普通索引 + 独立唯一约束」，两者对不上，
    # CI 的 alembic check 会判为模型漂移而失败。
    # 选择改模型而不是加一个改索引的迁移：语义完全等价（唯一性照样有），
    # 但在 MySQL 上重建这个索引要先绕开外键对索引的依赖（errno 1553）。
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    encrypted_key: Mapped[str] = mapped_column(Text)
    key_last4: Mapped[str] = mapped_column(String(4))
    key_fingerprint: Mapped[str] = mapped_column(String(64))

    # 只允许官方 DeepSeek 的两个模型，取值在 schemas 层用 Literal 卡死
    model: Mapped[str] = mapped_column(String(32), default="deepseek-chat")

    # 保存时做过一次轻量校验；之后每次真实调用也会回写状态
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_call_status: Mapped[str | None] = mapped_column(String(32))
    last_call_at: Mapped[datetime | None] = mapped_column(DateTime)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="model_config_row")

    # 一个用户一份配置。刻意不给名字：迁移 a421 里写的是匿名
    # sa.UniqueConstraint("user_id")，SQLite 把它编译进 CREATE TABLE 的
    # 内联 UNIQUE，反射不回名字。这边一旦命名，alembic check 就会把它
    # 判成「新增了一个约束」而让 CI 变红。
    __table_args__ = (UniqueConstraint("user_id"),)


# --------------------------------------------------------------------------- #
# 1c. 公告问答会话                                                              #
# --------------------------------------------------------------------------- #
class QASession(Base):
    """一次公告问答的会话。

    做成持久化而不是纯前端状态：用户换台设备、或者只是刷新了页面，
    之前问过什么、AI 依据哪条公告回答的，都该还在。
    """

    __tablename__ = "qa_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # 会话标题取自第一个问题，便于在列表里认出来
    title: Mapped[str | None] = mapped_column(String(128))
    # 从岗位详情页进来的会话记住是哪个岗位，后续提问自动带上该公告上下文。
    # 岗位被清理（如识别为非招聘内容）时置空而不是连带删会话——
    # 用户问过的话不该因为岗位下架而消失。
    job_id: Mapped[str | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    messages: Mapped[list["QAMessage"]] = relationship(
        back_populates="session", cascade="all, delete-orphan",
        order_by="QAMessage.created_at",
    )


class QAMessage(Base):
    """会话里的一条消息。用户提问与 AI 回答都存这里。"""

    __tablename__ = "qa_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("qa_sessions.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))  # user / assistant
    content: Mapped[str] = mapped_column(Text)
    # 回答的引用出处（[{job_id, title, snippet, score}, ...]）。
    # 存下来而不是每次重算：同一个问题重新检索未必命中同样的片段，
    # 那样历史记录里的"依据"就会和当初给用户看的不一致。
    sources: Mapped[list | None] = mapped_column(JSON)
    # 检索没命中时为 False。区分"AI 说不知道"和"AI 答了"，
    # 便于日后统计拒答率，也让前端能对拒答用不同样式。
    found: Mapped[bool | None] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    session: Mapped["QASession"] = relationship(back_populates="messages")


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
    # 单学科字段。历史遗留：早期假设"一个岗位一个学科"，靠在公告全文里
    # 找第一个命中的学科名来填。这个假设是错的——实测 12 条标为"语文"的
    # 岗位有 11 条其实是多学科招聘，只因为"语文"在标准表里排第一。
    # 保留它是为了去重指纹与老数据兼容；**筛选与展示一律用下面的 subjects**。
    subject: Mapped[str | None] = mapped_column(String(32), index=True)
    # 该公告实际招聘的全部学科，竖线包裹：'|语文|数学|'。
    # 见 services/taxonomy.pack_subjects——存串不存 JSON 是为了能在 SQL 里
    # 用 LIKE 筛，JSON 的包含查询在 SQLite 与 MySQL 上语法不一致。
    subjects: Mapped[str | None] = mapped_column(String(255), index=True)
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
    match_reason: Mapped[str | None] = mapped_column(Text)            # LLM 一句话综合理由
    # 命中点与差距是模型逐条给出的结构化结果，也是"这个分数怎么来的"的唯一依据。
    # 之前没有这两列，等于花 token 让模型算完再扔掉，推荐页只能给一个不可解释的分数。
    matched_points: Mapped[list | None] = mapped_column(JSON)         # ["学科匹配：语文", ...]
    gaps: Mapped[list | None] = mapped_column(JSON)                   # JD 要求但简历未体现的点
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
