"""登录接口：邮箱注册/登录为主，微信与访客保留。"""
import re
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from database import get_db
from deps import get_current_user
from models import User
from services import ratelimit
from services.auth import (
    hash_password, make_token, needs_rehash, verify_password, wechat_code_to_openid,
)

router = APIRouter(prefix="/auth", tags=["auth"])

# 不引 email-validator（那是额外依赖），用够用的正则挡住明显不是邮箱的输入。
# 真正的有效性只有发信才能证明，而本阶段不做邮箱验证，所以不假装能验真。
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$")
MIN_PASSWORD_LEN = 8


class RegisterIn(BaseModel):
    email: str
    password: str
    nickname: str | None = None

    @field_validator("email")
    @classmethod
    def _check_email(cls, v: str) -> str:
        v = v.strip().lower()  # 邮箱大小写不敏感，统一存小写避免重复注册
        if not _EMAIL_RE.match(v):
            raise ValueError("邮箱格式不正确")
        return v

    @field_validator("password")
    @classmethod
    def _check_password(cls, v: str) -> str:
        if len(v) < MIN_PASSWORD_LEN:
            raise ValueError(f"密码至少 {MIN_PASSWORD_LEN} 位")
        return v


class EmailLoginIn(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def _lower(cls, v: str) -> str:
        return v.strip().lower()


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _guard_rate(request: Request) -> None:
    """注册/登录都要限流。

    scrypt 每次要算 32MB 内存、约 46ms CPU——不限流的话，几十个并发
    请求就能把小内存机器打爆，等于把口令哈希的抗爆破特性反过来当成
    DoS 放大器。复用已有的 IP 限流，不另写一套。
    """
    if not ratelimit.check_ip_rate(_client_ip(request)):
        raise HTTPException(429, "请求过于频繁，请稍后再试")


def _session_payload(user: User) -> dict:
    return {
        "token": make_token(user.id),
        "user_id": user.id,
        "email": user.email,
        "nickname": user.nickname,
        "is_guest": user.is_guest,
    }


@router.post("/register")
def register(body: RegisterIn, request: Request, db: Session = Depends(get_db)):
    """邮箱注册。邮箱唯一，密码用 scrypt 哈希后存储。"""
    _guard_rate(request)

    exists = db.scalar(
        select(User).where(func.lower(User.email) == body.email)
    )
    if exists:
        # 这里刻意直说"已被注册"。严格来说这会泄漏"某邮箱是否注册过"，
        # 但注册表单本来就能通过"能不能注册成功"探测出同样的信息，
        # 含糊其辞只会让真实用户困惑而挡不住探测。
        raise HTTPException(409, "该邮箱已被注册")

    user = User(
        email=body.email,
        password_hash=hash_password(body.password),
        nickname=body.nickname or body.email.split("@")[0],
        is_guest=False,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return _session_payload(user)


@router.post("/login")
def login_email(body: EmailLoginIn, request: Request, db: Session = Depends(get_db)):
    """邮箱 + 密码登录。

    邮箱不存在与密码错误返回同一句提示：区分开就等于给爆破者一个
    "这个邮箱存在"的确认信号，让他们可以先枚举邮箱再集中猜密码。
    """
    _guard_rate(request)

    user = db.scalar(select(User).where(func.lower(User.email) == body.email))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "邮箱或密码不正确")

    # 透明升级：哈希参数调高后，老用户下次登录自动重算，无需改密码。
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
        db.commit()
        db.refresh(user)

    return _session_payload(user)


class WechatLoginIn(BaseModel):
    code: str  # 小程序 wx.login() 拿到的 code


@router.post("/wechat/login")
def login_wechat(body: WechatLoginIn, db: Session = Depends(get_db)):
    """微信登录：code → openid → 查/建用户 → 返回会话令牌。

    历史入口。邮箱体系上线后仍保留，已有微信用户不受影响；
    这类用户 email 为空，唯一索引允许多个 NULL 并存。
    """
    try:
        openid = wechat_code_to_openid(body.code)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"微信登录失败：{e}") from e

    user = db.scalar(select(User).where(User.openid == openid))
    if user is None:
        user = User(openid=openid, is_guest=False)
        db.add(user)
        db.commit()
        db.refresh(user)
    return _session_payload(user)


@router.post("/guest")
def guest_login(db: Session = Depends(get_db)):
    """免注册体验身份：可浏览岗位，但不能保存任何个人数据。

    刻意不收集真实身份（无手机号/邮箱），令牌丢了身份即弃。
    is_guest=True 是所有写接口的拦截依据，见 deps.require_registered_user。
    """
    user = User(
        openid=f"guest_{uuid4().hex[:24]}", nickname="体验用户", is_guest=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return _session_payload(user)


@router.get("/me")
def whoami(user: User = Depends(get_current_user)):
    """给前端判断当前登录态用；无效令牌返回 401 由前端引导登录。"""
    return _session_payload(user)
