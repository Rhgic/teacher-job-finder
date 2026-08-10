"""用户配置 / 简历 / 模板 接口（已实现 CRUD）。"""
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from database import get_db
from deps import get_current_user, require_registered_user
from models import User, UserProfile, Resume, Template
from schemas import (
    ProfileIn, ProfileOut, ResumeIn, ResumeOut, TemplateIn, TemplateOut,
)
from services import resume_extract
from services.resume_parser import parse_resume_pdf, structure_resume_text

router = APIRouter(tags=["profile"])


# ---------------- 用户配置 ----------------
@router.get("/profile", response_model=ProfileOut)
def get_profile(user: User = Depends(get_current_user)):
    if user.profile is None:
        # 空档案是"我的"页的正常初始状态；返回一个空对象，前端不必把首次
        # 进入当成错误，也不会在浏览器控制台留下无意义的 404。
        return ProfileOut()
    return user.profile


@router.put("/profile", response_model=ProfileOut)
def update_profile(
    body: ProfileIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_registered_user),
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
    user: User = Depends(require_registered_user),
):
    data = body.model_dump()
    if data.get("structured_content") is None:
        data["structured_content"] = parse_resume_pdf(data.get("file_url") or "")
    resume = Resume(user_id=user.id, **data)
    db.add(resume)
    db.commit()
    db.refresh(resume)
    return resume


@router.post("/resumes/upload", response_model=ResumeOut)
async def upload_resume(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_registered_user),
):
    """上传简历文件，抽取文本并结构化。支持 PDF / Word(.docx) / Markdown / txt。

    只做文本抽取与栏目切分，不调用 LLM——上传本身不该产生模型费用。
    抽取失败时把可读原因返回给用户（如"扫描件读不出文字，请改用粘贴"）。
    """
    data = await file.read()
    try:
        text = resume_extract.extract_text(file.filename or "", data)
    except resume_extract.ExtractError as exc:
        raise HTTPException(400, str(exc)) from exc

    structured = structure_resume_text(text)
    structured["简历全文"] = text  # 与网页粘贴入口保持同一字段，便于回填编辑

    # 新上传的作为默认简历，其余取消默认，避免多份都标默认时取哪份不确定
    for existing in user.resumes:
        existing.is_default = False
    resume = Resume(
        user_id=user.id,
        file_name=file.filename or "上传简历",
        file_url="",
        file_size=len(data),
        is_default=True,
        structured_content=structured,
    )
    db.add(resume)
    db.commit()
    db.refresh(resume)
    return resume


@router.delete("/resumes/{resume_id}")
def delete_resume(
    resume_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_registered_user),
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
    user: User = Depends(require_registered_user),
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
    user: User = Depends(require_registered_user),
):
    tpl = db.get(Template, template_id)
    if tpl is None or tpl.user_id != user.id:
        raise HTTPException(404, "模板不存在")
    db.delete(tpl)
    db.commit()
    return {"ok": True}
