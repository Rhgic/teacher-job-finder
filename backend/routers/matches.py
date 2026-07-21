"""推荐 / 匹配管道接口。"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, select
from sqlalchemy.orm import Session

from database import get_db
from deps import get_current_user, require_admin_token
from models import User, Job, MatchResult
from schemas import MatchOut
from services import pipeline

router = APIRouter(tags=["matches"])


@router.post("/matches/refresh")
def refresh_my_matches(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """只对当前用户的规则跑一遍匹配管道（规则粗筛 + LLM 精排）。

    与 /crawl/run 的全量管道分开：这里不触发爬虫、不碰别人的规则，
    因此可以放心暴露给已登录（含体验身份）的普通用户。
    """
    return pipeline.run_pipeline(db, user_id=user.id)


@router.get("/recommendations", response_model=list[MatchOut])
def recommendations(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    include_expired: bool = Query(False),
):
    """本人命中的岗位：当前可投岗位优先，其次按匹配分。"""
    today = date.today()
    expiry_rank = case(
        (Job.deadline.is_(None), 1),
        (Job.deadline < today, 2),
        else_=0,
    )
    q = (
        select(MatchResult)
        .join(Job, MatchResult.job_id == Job.id)
        .where(MatchResult.user_id == user.id, MatchResult.rule_passed.is_(True))
        .order_by(
            expiry_rank.asc(),
            # 不写 NULLS LAST：MySQL 不支持该语法。deadline 为空的行已被
            # expiry_rank 归到 rank 1，这里不会与非空行混排。
            Job.deadline.asc(),
            # llm_score 没有 CASE 兜底，且各库对 DESC 时 NULL 位置的默认行为
            # 不一致（MySQL/SQLite 排最后，PostgreSQL 排最前）。
            # 用 "是否为空" 作为前置排序键显式表达"未评分的排最后"，各库一致。
            MatchResult.llm_score.is_(None).asc(),
            MatchResult.llm_score.desc(),
            MatchResult.created_at.desc(),
        )
    )
    if not include_expired:
        q = q.where((Job.deadline.is_(None)) | (Job.deadline >= today))
    return db.scalars(q).all()


@router.post("/pipeline/run")
def run_pipeline(
    _: None = Depends(require_admin_token),
    db: Session = Depends(get_db),
):
    """手动触发匹配管道（阶段 6 接调度后改为自动触发）。"""
    return pipeline.run_pipeline(db)


@router.post("/matches/{match_id}/tailor")
def tailor_for_match(
    match_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """为某条匹配按需生成改写简历草稿（draft，需用户审核）。"""
    match = db.get(MatchResult, match_id)
    if match is None or match.user_id != user.id:
        raise HTTPException(404, "匹配不存在")
    try:
        version = pipeline.generate_tailored_resume(db, match)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {
        "resume_version_id": version.id,
        "change_summary": version.change_summary,
        "status": version.status.value,
    }
