"""Run a bounded compliant crawl once, then optionally refresh matches.

Intended for systemd timer / cron. It does not run forever.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database import SessionLocal, init_db
from services import pipeline
from services.crawler import (
    BaseCrawler,
    ShenzhenEduBureauCrawler,
    ShenzhenTeacherTalentCrawler,
    ShenzhenTeacherRecruitCrawler,
    upsert_jobs,
)


CRAWLERS: dict[str, type[BaseCrawler]] = {
    "sz910": ShenzhenTeacherTalentCrawler,
    "shenzhenjiaoshi": ShenzhenTeacherRecruitCrawler,
    "sz_edu_bureau": ShenzhenEduBureauCrawler,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run teacher job crawler once.")
    parser.add_argument(
        "--source",
        choices=["sz910", "shenzhenjiaoshi", "sz_edu_bureau", "all"],
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
    return parser.parse_args()


def run_once(args: argparse.Namespace) -> dict:
    selected = CRAWLERS.items() if args.source == "all" else [(args.source, CRAWLERS[args.source])]
    init_db()

    fetched_total = 0
    upsert_total = {"new": 0, "updated": 0}
    errors: dict[str, str] = {}
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
                continue

            fetched_total += len(raws)
            result = upsert_jobs(db, raws)
            upsert_total["new"] += result["new"]
            upsert_total["updated"] += result["updated"]

        match_result = None if args.no_match else pipeline.run_pipeline(db)

    return {
        "source": args.source,
        "fetched": fetched_total,
        "upsert": upsert_total,
        "match": match_result,
        "errors": errors,
        "policies": policies,
    }


def main() -> int:
    args = parse_args()
    result = run_once(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["errors"] and result["fetched"] == 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
