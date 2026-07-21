"""登录接口。"""
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import get_db
from models import User
from services.auth import wechat_code_to_openid, make_token

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginIn(BaseModel):
    code: str  # 小程序 wx.login() 拿到的 code


@router.post("/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    """微信登录：code → openid → 查/建用户 → 返回会话令牌。"""
    try:
        openid = wechat_code_to_openid(body.code)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"微信登录失败：{e}") from e

    user = db.scalar(select(User).where(User.openid == openid))
    if user is None:
        user = User(openid=openid)
        db.add(user)
        db.commit()
        db.refresh(user)
    return {"token": make_token(user.id), "user_id": user.id}


@router.post("/guest")
def guest_login(db: Session = Depends(get_db)):
    """Web 端免注册体验身份。

    创建一个匿名用户并签发与微信登录同一套 HMAC 会话令牌，
    之后该访客的简历/规则/匹配都隔离在自己名下。
    刻意不收集任何真实身份信息（无手机号/邮箱），令牌丢了身份即弃。
    openid 用 guest_ 前缀命名空间，与微信 openid 不会冲突。
    """
    user = User(openid=f"guest_{uuid4().hex[:24]}", nickname="体验用户")
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"token": make_token(user.id), "user_id": user.id, "nickname": user.nickname}
