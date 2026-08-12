"""自动化匹配管道编排（已实现结构，调用各 service）。

流程：对每条 active 订阅规则 → 跑第一层规则过滤 → 命中的跑第二层 LLM 匹配
→ 写入 match_results（幂等：同 rule×job 不重复）。
简历改写默认不在管道内批量触发（成本/时延考虑），改在用户点开推荐时按需触发——
见 generate_tailored_resume()。
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import date

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from models import (
    SubRule, Job, Resume, MatchResult, MatchStatus, ResumeVersion, ResumeVersionStatus,
)
from services import llm_credentials
from services.llm_credentials import LLMCredential
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


def run_pipeline(db: Session, job_ids: list[str] | None = None,
                 user_id: str | None = None,
                 on_progress: Callable[[int, int], None] | None = None,
                 *, cred: LLMCredential | None = None) -> dict:
    """对(可选指定的)岗位跑 active 规则。返回统计。

    user_id 给定时只跑该用户的规则——Web 体验用户"运行匹配"走这里，
    不给普通访客触发全量管道的能力。

    on_progress(done, total) 在每次 LLM 调用后回调，用于异步任务上报进度。

    cred 不给时按 user_id 现场解析——worker 就走这条路：任务载荷里只有
    user_id，Key 由 worker 自己从库里读出来解密，不经过 Redis。
    user_id 也没有（管理员/定时任务跑全量）时，**按每条规则各自的主人**
    解析凭据——自带 Key 模式下"用谁的 Key 跑全量"没有统一答案，
    只能谁的规则花谁的额度。主人没配 Key 的规则整条跳过并计入
    skipped_no_key，而不是悄悄用 stub 生成一批假分数糊弄过去。
    """
    # 显式传入的凭据优先（在线请求已经解析过，不必再查一次库）
    cred_cache: dict[str, LLMCredential | None] = {}

    def cred_for(owner_id: str) -> LLMCredential | None:
        """返回该用户的凭据；没配 Key 返回 None（调用方跳过）。"""
        if cred is not None:
            return cred
        if owner_id not in cred_cache:
            try:
                cred_cache[owner_id] = llm_credentials.resolve_for_user(db, owner_id)
            except (llm_credentials.NoUserKey, llm_credentials.UserKeyUnreadable):
                cred_cache[owner_id] = None
        return cred_cache[owner_id]

    rule_q = select(SubRule).where(SubRule.is_active.is_(True))
    if user_id:
        rule_q = rule_q.where(SubRule.user_id == user_id)
    rules = db.scalars(rule_q).all()

    job_q = select(Job)
    if job_ids:
        job_q = job_q.where(Job.id.in_(job_ids))
    jobs = db.scalars(job_q).all()
    today = date.today()

    # 先把要评的 (rule, job) 全列出来，再逐个调模型。分成两趟是为了
    # 提前知道总数：进度要有分母，而"这次要花多少次模型调用"本身
    # 也是该在开跑前就能看到的量，而不是跑完才知道。
    todo: list[tuple[SubRule, Job]] = []
    for rule in rules:
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
            todo.append((rule, job))

    total = len(todo)
    if on_progress:
        on_progress(0, total)

    summaries: dict[str, str] = {}
    created = 0
    skipped = 0
    skipped_no_key = 0
    for done, (rule, job) in enumerate(todo, start=1):
        # 谁的规则花谁的额度。主人没配 Key 就整条跳过——不生成假分数。
        rule_cred = cred_for(rule.user_id)
        if rule_cred is None:
            skipped_no_key += 1
            if on_progress:
                on_progress(done, total)
            continue

        if rule.id not in summaries:
            summaries[rule.id] = _resume_summary_for(rule)
        intent = rule.user.profile.intent if rule.user.profile else None

        # 第二层：LLM 匹配
        result = match_resume_to_job(summaries[rule.id], job.description or "",
                                     intent, cred=rule_cred)
        try:
            # 预查询只能减少重复调用，不能作为并发下的唯一保证。
            # savepoint 让唯一约束冲突只回滚当前这一条，不污染整个 Session。
            with db.begin_nested():
                db.add(MatchResult(
                    rule_id=rule.id, job_id=job.id, user_id=rule.user_id,
                    rule_passed=True,
                    llm_score=result.get("score"),
                    match_reason=result.get("reason"),
                    # 模型已经按条给出了命中点和差距，token 也付过了——不存下来
                    # 推荐页就只剩一个没法解释的分数。
                    matched_points=result.get("matched_points") or None,
                    gaps=result.get("gaps") or None,
                    cover_letter=result.get("cover_letter"),
                    status=MatchStatus.PENDING_PUSH,
                ))
                db.flush()
        except IntegrityError:
            # 另一个 worker 已先落库，这是正常的并发结果。
            skipped += 1
        else:
            # 每次模型调用后立即持久化：后续单条失败不能丢掉已付费结果。
            db.commit()
            created += 1
        if on_progress:
            on_progress(done, total)

    return {
        "rules": len(rules), "jobs": len(jobs),
        "new_matches": created, "skipped": skipped,
        # 主人没配 Key 而被跳过的条数。单列出来，避免"跑完 0 条新匹配"
        # 被当成"没有合适岗位"——那是两件完全不同的事。
        "skipped_no_key": skipped_no_key,
    }


def generate_tailored_resume(db: Session, match: MatchResult,
                             *, cred: LLMCredential | None = None) -> ResumeVersion:
    """为某条匹配按需生成改写简历草稿（draft，需用户审核后才可投递）。

    凭据按 match.user_id 解析——改写的是谁的简历，就花谁的额度。
    """
    resumes = db.scalars(select(Resume).where(Resume.user_id == match.user_id)).all()
    base = next((r for r in resumes if r.is_default), resumes[0] if resumes else None)
    if base is None or not base.structured_content:
        raise ValueError("用户无结构化简历，无法改写。请先补全 structured_content。")

    if cred is None:
        cred = llm_credentials.resolve_for_user(db, match.user_id)

    job = db.get(Job, match.job_id)
    out = tailor_resume(base.structured_content, job.description or "", cred=cred)

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
