"""用户轻量设置接口：保存搜索、材料清单等小工具状态。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import get_db
from deps import get_current_user
from models import User, UserSetting
from schemas import SettingIn, SettingOut

router = APIRouter(prefix="/settings", tags=["settings"])

ALLOWED_KEYS = {
    "saved_searches",
    "materials_checklist",
    "favorite_jobs",
    "local_applications",
    "notification_preferences",
}


def _ensure_key(key: str) -> None:
    if key not in ALLOWED_KEYS:
        raise HTTPException(404, "设置项不存在")


@router.get("/{key}", response_model=SettingOut)
def get_setting(
    key: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _ensure_key(key)
    setting = db.scalar(
        select(UserSetting).where(UserSetting.user_id == user.id, UserSetting.key == key)
    )
    if setting is None:
        return SettingOut(
            key=key,
            value=[]
            if key in {"saved_searches", "materials_checklist", "favorite_jobs", "local_applications"}
            else {},
        )
    return setting


@router.put("/{key}", response_model=SettingOut)
def put_setting(
    key: str,
    body: SettingIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _ensure_key(key)
    setting = db.scalar(
        select(UserSetting).where(UserSetting.user_id == user.id, UserSetting.key == key)
    )
    if setting is None:
        setting = UserSetting(user_id=user.id, key=key)
    setting.value = body.value
    db.add(setting)
    db.commit()
    db.refresh(setting)
    return setting
