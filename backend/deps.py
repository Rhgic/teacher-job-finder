"""共享依赖：当前用户。

优先用 Authorization: Bearer <token> 解析真实登录态；
AUTH_DEV_MODE=1 且无令牌时回退 demo 用户，便于本地联调（生产置 0）。
"""
from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from models import User
from services.auth import verify_token


def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    if authorization and authorization.lower().startswith("bearer "):
        user_id = verify_token(authorization[7:].strip())
        if user_id:
            user = db.get(User, user_id)
            if user:
                return user
        raise HTTPException(401, "登录态无效，请重新登录")

    if settings.AUTH_DEV_MODE:
        user = db.scalar(select(User).where(User.openid == "demo_openid_0001"))
        if user is None:
            raise HTTPException(404, "demo 用户不存在，请先运行 python seed.py")
        return user

    raise HTTPException(401, "需要登录")


def require_registered_user(user: User = Depends(get_current_user)) -> User:
    """写操作的准入：访客只能读，不能保存任何个人数据。

    拦在依赖层而不是每个接口里各写一遍 if——后者迟早会漏掉一个新接口，
    而漏掉的那个就是数据越界的入口。

    返回 401 而非 403：前端据此弹登录框。403 语义是"你已表明身份但无权"，
    访客的正确出路是先注册，属于"尚未表明身份"。
    """
    if user.is_guest:
        raise HTTPException(
            401,
            "体验身份不能保存数据，请先注册或登录",
        )
    return user


def require_admin_token(x_admin_token: str | None = Header(default=None)) -> None:
    """生产环境保护后台任务入口，避免公开域名被外部反复调用。"""
    if settings.AUTH_DEV_MODE:
        return
    if not settings.ADMIN_API_TOKEN:
        raise HTTPException(503, "管理令牌未配置，不能触发后台任务")
    if x_admin_token != settings.ADMIN_API_TOKEN:
        raise HTTPException(403, "无权触发后台任务")
