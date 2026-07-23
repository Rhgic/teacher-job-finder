"""Run a bounded compliant crawl once, then optionally refresh matches.

Intended for systemd timer / cron. It does not run forever.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database import SessionLocal, init_db
from observability import setup_logging
from services import pipeline
from services.crawler import (
    BaseCrawler,
    ShenzhenEduBureauCrawler,
    ShenzhenTeacherTalentCrawler,
    ShenzhenTeacherRecruitCrawler,
    upsert_jobs,
)


logger = logging.getLogger("crawl")

CRAWLERS: dict[str, type[BaseCrawler]] = {
    "sz910": ShenzhenTeacherTalentCrawler,
    "shenzhenjiaoshi": ShenzhenTeacherRecruitCrawler,
    "sz_edu_bureau": ShenzhenEduBureauCrawler,
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """argv 留给测试注入；命令行下走 sys.argv。"""
    parser = argparse.ArgumentParser(description="Run teacher job crawler once.")
    parser.add_argument(
        "--source",
        # 从 CRAWLERS 推导而非另写一份：新增爬虫时只改一处，
        # 也让测试能注入假源。
        choices=[*CRAWLERS, "all"],
        default="sz910",
        help="Crawler source to run. Default: sz910",
    )
    parser.add_argument(
        "--max-detail-pages",
        type=int,
        default=12,
        help="Maximum detail pages per source. Default: 12",
    )
    parser.add_argument(
        "--no-match",
        action="store_true",
        help="Only crawl/upsert jobs; skip recommendation pipeline.",
    )
    return parser.parse_args(argv)


def run_once(args: argparse.Namespace) -> dict:
    selected = CRAWLERS.items() if args.source == "all" else [(args.source, CRAWLERS[args.source])]
    init_db()

    fetched_total = 0
    upsert_total = {"new": 0, "updated": 0}
    errors: dict[str, str] = {}
    empty_sources: list[str] = []
    policies: dict[str, dict] = {}

    with SessionLocal() as db:
        for name, crawler_cls in selected:
            crawler = crawler_cls()
            if hasattr(crawler, "max_detail_pages"):
                crawler.max_detail_pages = args.max_detail_pages
            policies[name] = {
                "source": crawler.source,
                "obey_robots": crawler.obey_robots,
                "min_interval_sec": crawler.min_interval_sec,
                "cache_ttl_sec": crawler.cache_ttl_sec,
            }
            try:
                raws = crawler.fetch()
            except Exception as exc:  # noqa: BLE001 - scheduled job should report and continue.
                errors[name] = f"{type(exc).__name__}: {exc}"
                logger.error("crawl_source_failed", extra={"extra_fields": {
                    "source": name, "error": f"{type(exc).__name__}: {exc}"}})
                continue

            # 抓到 0 条不会抛异常，定时任务照常"成功"退出——
            # 这些站点是 HTML 解析，改版后爬虫会静默返回空，
            # 数据悄悄停止增长而没有任何信号。静默失败比崩溃更难发现，
            # 所以这里显式记 ERROR，让日志与告警能抓到。
            if not raws:
                empty_sources.append(name)
                logger.error("crawl_returned_nothing", extra={"extra_fields": {
                    "source": name,
                    "hint": "可能是站点改版导致解析失效，或 robots/网络异常，请人工核查",
                }})

            fetched_total += len(raws)
            result = upsert_jobs(db, raws)
            upsert_total["new"] += result["new"]
            upsert_total["updated"] += result["updated"]

        match_result = None if args.no_match else pipeline.run_pipeline(db)

    if empty_sources:
        logger.error("crawl_has_empty_sources", extra={"extra_fields": {
            "empty_sources": empty_sources, "total_sources": len(selected)}})

    return {
        "empty_sources": empty_sources,
        "source": args.source,
        "fetched": fetched_total,
        "upsert": upsert_total,
        "match": match_result,
        "errors": errors,
        "policies": policies,
    }


def main() -> int:
    # 定时任务独立于 API 进程运行，日志要自己初始化，
    # 否则上面记的 ERROR 不会以 JSON 格式进 journald，告警也就抓不到。
    setup_logging()
    args = parse_args()
    result = run_once(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    # 退出码语义：
    # 1 = 全部源都抓不到东西（真故障，systemd 会标记失败）
    # 0 = 至少一个源有产出；部分源为空已记 ERROR 日志，不让整个任务算失败，
    #     否则一个站点改版就会淹没掉其它源正常工作的信号
    if result["errors"] and result["fetched"] == 0:
        return 1
    if result["empty_sources"] and result["fetched"] == 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
