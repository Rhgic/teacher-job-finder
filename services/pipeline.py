from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import Job, MatchResult, Resume, SubRule, User, UserProfile
from services.llm_match import match_job
from services.rule_filter import rule_matches_job


def run_pipeline(db: Session, user_openid: str | None = None) -> dict[str, int]:
    rules_stmt = select(SubRule).where(SubRule.active.is_(True))
    if user_openid:
        rules_stmt = rules_stmt.join(User).where(User.openid == user_openid)

    rules = db.scalars(rules_stmt).all()
    jobs = db.scalars(select(Job)).all()

    checked = 0
    rule_hits = 0
    created = 0
    updated = 0

    for rule in rules:
        user = db.get(User, rule.user_id)
        profile = db.scalar(select(UserProfile).where(UserProfile.user_id == rule.user_id))
        resume = db.scalar(
            select(Resume)
            .where(Resume.user_id == rule.user_id)
            .order_by(Resume.is_default.desc(), Resume.created_at.desc())
        )
        for job in jobs:
            checked += 1
            if not rule_matches_job(rule, job):
                continue
            rule_hits += 1
            exists = db.scalar(
                select(MatchResult).where(
                    MatchResult.rule_id == rule.id,
                    MatchResult.job_id == job.id,
                )
            )
            output = match_job(job, rule, profile, resume)
            if exists:
                exists.llm_score = output.score
                exists.matched_points = output.matched_points
                exists.gaps = output.gaps
                exists.reason = output.reason
                exists.cover_letter = output.cover_letter
                db.add(exists)
                updated += 1
                continue
            result = MatchResult(
                rule_id=rule.id,
                job_id=job.id,
                user_id=rule.user_id,
                llm_score=output.score,
                matched_points=output.matched_points,
                gaps=output.gaps,
                reason=output.reason,
                cover_letter=output.cover_letter,
            )
            db.add(result)
            created += 1
        if user:
            db.add(user)
    db.commit()
    return {
        "rules": len(rules),
        "jobs": len(jobs),
        "checked": checked,
        "rule_hits": rule_hits,
        "created": created,
        "updated": updated,
    }
