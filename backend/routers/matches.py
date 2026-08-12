"""推荐 / 匹配管道接口。"""
import asyncio
import functools
import time
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import case, select
from sqlalchemy.orm import Session

from database import get_db
from deps import require_admin_token, require_registered_user
from models import User, Job, MatchResult
from schemas import MatchOut
from services import llm_credentials, pipeline, ratelimit, tasks
from services.llm_errors import raise_for_missing_key

router = APIRouter(tags=["matches"])


@router.post("/matches/refresh")
async def refresh_my_matches(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_registered_user),
):
    """只对当前用户的规则跑一遍匹配管道（规则粗筛 + LLM 精排）。

    与 /crawl/run 的全量管道分开：这里不触发爬虫、不碰别人的规则，
    因此可以放心暴露给已登录（含体验身份）的普通用户。

    一次刷新可能对几十个候选岗位逐个调模型，比单次问答更烧钱，
    所以配额按次扣在这里，规则层粗筛掉的岗位不计入。

    **入队而不是当场跑完。** 几十次串行模型调用要几十秒，占着请求线程
    等于让网关和用户一起干等，超时断开后这次调用的钱照样已经付了。
    这里只负责入队并立刻返回任务 ID，进度由 GET /matches/refresh/{task_id} 轮询。

    队列不可用时退回同步执行（mode=sync）：异步是体验优化，
    不能因为 Redis 挂了就让用户连匹配都跑不了。
    """
    ip = request.client.host if request.client else ""
    if not ratelimit.check_ip_rate(ip):
        raise HTTPException(429, "请求过于频繁，请稍后再试")

    # 入队前先确认凭据可用。否则任务进了队列、worker 才发现没 Key，
    # 用户看到的是一个跑了很久然后失败的任务，而不是当场的引导。
    raise_for_missing_key(lambda: llm_credentials.resolve_for_user(db, user.id))

    enqueue = await tasks.enqueue_refresh(user.id)
    if enqueue:
        # 只有确认创建了新任务才扣配额；重复点击只继续轮询原任务。
        if enqueue.is_new:
            verdict = ratelimit.check_and_consume_llm_quota(user.id)
            if not verdict.allowed:
                tasks.set_state(
                    enqueue.task_id, status="rejected",
                    message="今日匹配额度已用完，请明天再来",
                )
                raise HTTPException(429, (
                    "今日匹配次数已用完，请明天再来"
                    if verdict.reason == "user_quota_exceeded"
                    else "演示环境今日额度已用完，请明天再来"
                ))
            tasks.set_state(
                enqueue.task_id, status="queued", queued_at=int(time.time()),
            )
        state = tasks.read_state(enqueue.task_id) or {}
        if state.get("status") == "rejected":
            raise HTTPException(429, state.get("message") or "今日匹配额度已用完")
        return {
            "mode": "async", "task_id": enqueue.task_id,
            "status": state.get("status", "queued"),
        }

    # 队列不可用但仍要跑同步任务，因此同样要扣一次配额。
    verdict = ratelimit.check_and_consume_llm_quota(user.id)
    if not verdict.allowed:
        raise HTTPException(429, (
            "今日匹配次数已用完，请明天再来"
            if verdict.reason == "user_quota_exceeded"
            else "演示环境今日额度已用完，请明天再来"
        ))

    # 同步兜底。放线程里跑，别把事件循环卡死拖累其它请求。
    cred = raise_for_missing_key(lambda: llm_credentials.resolve_for_user(db, user.id))
    stats = await asyncio.to_thread(
        functools.partial(pipeline.run_pipeline, db, None, user.id, cred=cred))
    return {"mode": "sync", "status": "done", **stats}


@router.get("/matches/refresh/{task_id}")
def refresh_status(
    task_id: str,
    user: User = Depends(require_registered_user),
):
    """轮询刷新任务进度。

    状态里带 user_id 并在这里核对：task_id 是可猜的字符串，
    不校验归属就等于凭 ID 能读到别人的匹配结果。
    归属不符时按"不存在"处理，不区分两种情况——否则这个接口
    就成了探测他人任务 ID 是否有效的工具。
    """
    state = tasks.read_state(task_id)
    if state is None or state.get("user_id") != user.id:
        raise HTTPException(404, "任务不存在或已过期")
    # user_id 是校验用的内部字段，对客户端没用途，不回显
    return {"task_id": task_id, **{k: v for k, v in state.items() if k != "user_id"}}


@router.get("/recommendations", response_model=list[MatchOut])
def recommendations(
    db: Session = Depends(get_db),
    user: User = Depends(require_registered_user),
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
    user: User = Depends(require_registered_user),
):
    """为某条匹配按需生成改写简历草稿（draft，需用户审核）。"""
    match = db.get(MatchResult, match_id)
    if match is None or match.user_id != user.id:
        raise HTTPException(404, "匹配不存在")
    try:
        cred = raise_for_missing_key(
            lambda: llm_credentials.resolve_for_user(db, user.id))
        version = pipeline.generate_tailored_resume(db, match, cred=cred)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {
        "resume_version_id": version.id,
        "change_summary": version.change_summary,
        "status": version.status.value,
    }
