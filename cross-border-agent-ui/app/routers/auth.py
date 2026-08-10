"""登录、当前用户、角色依赖。

其它 router 从这里取 get_current_user / require_admin，
保证"取当前用户"和"校验角色"只有一处实现。
"""

from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import Tenant, User
from app.schemas import LoginRequest, MeResponse, TokenResponse

router = APIRouter(prefix="/api", tags=["auth"])
settings = get_settings()
# auto_error=False：缺 token 时由我们统一返回 401 结构，而不是 FastAPI 的默认 403
bearer = HTTPBearer(auto_error=False)

ROLE_ADMIN = "admin"
ROLE_AGENT = "agent"


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except ValueError:
        # 哈希串格式异常时按验证失败处理，不让异常冒出去变成 500
        return False


def create_token(user: User) -> tuple[str, int]:
    expire_seconds = settings.jwt_expire_minutes * 60
    payload = {
        "sub": str(user.id),
        "role": user.role,
        "tid": user.tenant_id,
        "exp": datetime.now(UTC) + timedelta(minutes=settings.jwt_expire_minutes),
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, expire_seconds


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if creds is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未提供凭证")
    try:
        payload = jwt.decode(
            creds.credentials, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
    except jwt.PyJWTError:
        # 不回显具体解码错误：过期/签名错/格式错对调用方是同一件事
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="凭证无效或已过期"
        ) from None

    user = db.get(User, int(payload.get("sub", 0)))
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不可用")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    """审批类操作专用。客服能处理会话，但不能给自己的高风险草稿放行。"""
    if user.role != ROLE_ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限才能审批")
    return user


@router.post("/auth/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    # V1 只有一个租户，所以按用户名全局查即可。
    # 注意：唯一约束已是 (tenant_id, username)，真正多租户上线时这里必须
    # 改成先定位租户（子域名 / 登录表单选择）再查用户，否则同名账号会撞。
    user = db.scalar(select(User).where(User.username == payload.username).order_by(User.id))
    # 用户不存在与密码错误返回同一句话，避免通过响应差异枚举用户名
    ok = (
        user is not None
        and user.is_active
        and verify_password(payload.password, user.password_hash)
    )
    if not ok:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    token, expires_in = create_token(user)
    return TokenResponse(
        access_token=token,
        expires_in=expires_in,
        role=user.role,
        username=user.username,
    )


@router.get("/auth/me", response_model=MeResponse)
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> MeResponse:
    tenant = db.get(Tenant, user.tenant_id)
    return MeResponse(
        id=user.id,
        username=user.username,
        role=user.role,
        tenant_id=user.tenant_id,
        tenant_name=tenant.name if tenant else "",
    )
