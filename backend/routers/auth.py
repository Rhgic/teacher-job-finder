"""登录接口。"""
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
        raise HTTPException(400, f"微信登录失败：{e}")

    user = db.scalar(select(User).where(User.openid == openid))
    if user is None:
        user = User(openid=openid)
        db.add(user)
        db.commit()
        db.refresh(user)
    return {"token": make_token(user.id), "user_id": user.id}
