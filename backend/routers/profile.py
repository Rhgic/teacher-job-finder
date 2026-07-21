"""用户配置 / 简历 / 模板 接口（已实现 CRUD）。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from deps import get_current_user
from models import User, UserProfile, Resume, Template
from schemas import (
    ProfileIn, ProfileOut, ResumeIn, ResumeOut, TemplateIn, TemplateOut,
)
from services.resume_parser import parse_resume_pdf

router = APIRouter(tags=["profile"])


# ---------------- 用户配置 ----------------
@router.get("/profile", response_model=ProfileOut)
def get_profile(user: User = Depends(get_current_user)):
    if user.profile is None:
        raise HTTPException(404, "尚未填写求职信息")
    return user.profile


@router.put("/profile", response_model=ProfileOut)
def update_profile(
    body: ProfileIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    profile = user.profile or UserProfile(user_id=user.id)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(profile, k, v)
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


# ---------------- 简历 ----------------
@router.get("/resumes", response_model=list[ResumeOut])
def list_resumes(user: User = Depends(get_current_user)):
    return user.resumes


@router.post("/resumes", response_model=ResumeOut)
def create_resume(
    body: ResumeIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    data = body.model_dump()
    if data.get("structured_content") is None:
        data["structured_content"] = parse_resume_pdf(data.get("file_url") or "")
    resume = Resume(user_id=user.id, **data)
    db.add(resume)
    db.commit()
    db.refresh(resume)
    return resume


@router.delete("/resumes/{resume_id}")
def delete_resume(
    resume_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    resume = db.get(Resume, resume_id)
    if resume is None or resume.user_id != user.id:
        raise HTTPException(404, "简历不存在")
    db.delete(resume)
    db.commit()
    return {"ok": True}


# ---------------- 模板 ----------------
@router.get("/templates", response_model=list[TemplateOut])
def list_templates(user: User = Depends(get_current_user)):
    return user.templates


@router.post("/templates", response_model=TemplateOut)
def create_template(
    body: TemplateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    tpl = Template(user_id=user.id, **body.model_dump())
    db.add(tpl)
    db.commit()
    db.refresh(tpl)
    return tpl


@router.delete("/templates/{template_id}")
def delete_template(
    template_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    tpl = db.get(Template, template_id)
    if tpl is None or tpl.user_id != user.id:
        raise HTTPException(404, "模板不存在")
    db.delete(tpl)
    db.commit()
    return {"ok": True}
