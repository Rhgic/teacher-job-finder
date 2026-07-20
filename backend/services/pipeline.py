"""自动化匹配管道编排（已实现结构，调用各 service）。

流程：对每条 active 订阅规则 → 跑第一层规则过滤 → 命中的跑第二层 LLM 匹配
→ 写入 match_results（幂等：同 rule×job 不重复）。
简历改写默认不在管道内批量触发（成本/时延考虑），改在用户点开推荐时按需触发——
见 generate_tailored_resume()。
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import (
    SubRule, Job, Resume, MatchResult, MatchStatus, ResumeVersion, ResumeVersionStatus,
)
from services.rule_filter import rule_matches_job
from services.llm_match import match_resume_to_job
from services.resume_tailor import tailor_resume


def _resume_summary_for(rule: SubRule) -> str:
    """取该用户默认简历的结构化内容做摘要，喂给 LLM。"""
    profile = rule.user.profile
    resumes = [r for r in rule.user.resumes if r.is_default] or rule.user.resumes
    base = resumes[0].structured_content if resumes else None
    parts = []
    if profile:
        parts.append(f"{profile.real_name or ''} {profile.education or ''} {profile.major or ''} {profile.subject or ''}")
    if base:
        parts.append(str(base))
    return " | ".join(p for p in parts if p.strip())


def run_pipeline(db: Session, job_ids: list[str] | None = None) -> dict:
    """对(可选指定的)岗位跑全部 active 规则。返回统计。"""
    rules = db.scalars(select(SubRule).where(SubRule.is_active.is_(True))).all()

    job_q = select(Job)
    if job_ids:
        job_q = job_q.where(Job.id.in_(job_ids))
    jobs = db.scalars(job_q).all()
    today = date.today()

    created = 0
    for rule in rules:
        resume_summary = _resume_summary_for(rule)
        intent = rule.user.profile.intent if rule.user.profile else None
        for job in jobs:
            if job.deadline and job.deadline < today:
                continue
            # 幂等：该 rule×job 已评过就跳过
            exists = db.scalar(
                select(MatchResult).where(
                    MatchResult.rule_id == rule.id, MatchResult.job_id == job.id
                )
            )
            if exists:
                continue
            if not rule_matches_job(rule, job):
                continue  # 第一层未过，直接丢弃（不入库）

            # 第二层：LLM 匹配
            result = match_resume_to_job(resume_summary, job.description or "", intent)
            db.add(MatchResult(
                rule_id=rule.id, job_id=job.id, user_id=rule.user_id,
                rule_passed=True,
                llm_score=result.get("score"),
                match_reason=result.get("reason"),
                cover_letter=result.get("cover_letter"),
                status=MatchStatus.PENDING_PUSH,
            ))
            created += 1

    db.commit()
    return {"rules": len(rules), "jobs": len(jobs), "new_matches": created}


def generate_tailored_resume(db: Session, match: MatchResult) -> ResumeVersion:
    """为某条匹配按需生成改写简历草稿（draft，需用户审核后才可投递）。"""
    resumes = db.scalars(select(Resume).where(Resume.user_id == match.user_id)).all()
    base = next((r for r in resumes if r.is_default), resumes[0] if resumes else None)
    if base is None or not base.structured_content:
        raise ValueError("用户无结构化简历，无法改写。请先补全 structured_content。")

    job = db.get(Job, match.job_id)
    out = tailor_resume(base.structured_content, job.description or "")

    version = ResumeVersion(
        user_id=match.user_id, base_resume_id=base.id, match_id=match.id, job_id=job.id,
        tailored_content=out.get("tailored_content"),
        change_summary="\n".join(out.get("change_summary", [])),
        status=ResumeVersionStatus.DRAFT,
    )
    db.add(version)
    db.commit()
    db.refresh(version)
    return version
