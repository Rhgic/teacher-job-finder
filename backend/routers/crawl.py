"""手动抓取岗位入口。

阶段 6 可以把这里接到定时任务；当前先保留人工/后台触发，便于验证来源。
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database import get_db
from deps import require_admin_token
from services import pipeline
from services.crawler import (
    BaseCrawler,
    ShenzhenEduBureauCrawler,
    ShenzhenTeacherTalentCrawler,
    ShenzhenTeacherRecruitCrawler,
    upsert_jobs,
)

router = APIRouter(prefix="/crawl", tags=["crawl"])


CRAWLERS: dict[str, type[BaseCrawler]] = {
    "sz910": ShenzhenTeacherTalentCrawler,
    "shenzhenjiaoshi": ShenzhenTeacherRecruitCrawler,
    "sz_edu_bureau": ShenzhenEduBureauCrawler,
}


def _crawler_policy(crawler: BaseCrawler) -> dict:
    return {
        "source": crawler.source,
        "obey_robots": crawler.obey_robots,
        "min_interval_sec": crawler.min_interval_sec,
        "cache_ttl_sec": crawler.cache_ttl_sec,
    }


@router.get("/sources")
def list_sources():
    """列出当前启用的抓取源和合规策略，便于上线前核对。"""
    return {
        name: _crawler_policy(crawler_cls())
        for name, crawler_cls in CRAWLERS.items()
    }


@router.post("/run")
def run_crawl(
    source: str = Query("sz910", pattern="^(sz910|shenzhenjiaoshi|sz_edu_bureau|all)$"),
    max_detail_pages: int = Query(12, ge=1, le=50),
    run_match: bool = True,
    _: None = Depends(require_admin_token),
    db: Session = Depends(get_db),
):
    """抓取岗位并入库；默认抓深圳教师人才网，随后触发匹配管道。"""
    selected = CRAWLERS.items() if source == "all" else [(source, CRAWLERS[source])]
    fetched_total = 0
    upsert_total = {"new": 0, "updated": 0}
    errors: dict[str, str] = {}
    policies: dict[str, dict] = {}

    for name, crawler_cls in selected:
        crawler = crawler_cls()
        policies[name] = _crawler_policy(crawler)
        if hasattr(crawler, "max_detail_pages"):
            crawler.max_detail_pages = max_detail_pages
        try:
            raws = crawler.fetch()
        except Exception as exc:
            errors[name] = str(exc)
            continue

        fetched_total += len(raws)
        result = upsert_jobs(db, raws)
        upsert_total["new"] += result["new"]
        upsert_total["updated"] += result["updated"]

    if fetched_total == 0 and errors:
        raise HTTPException(502, {"message": "抓取失败，外部站点可能暂时不可用", "errors": errors})

    match_result = pipeline.run_pipeline(db) if run_match else None
    return {
        "source": source,
        "fetched": fetched_total,
        "upsert": upsert_total,
        "match": match_result,
        "errors": errors,
        "policies": policies,
    }
