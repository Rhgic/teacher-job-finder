"""清理库里已入库的非招聘内容。

爬虫的标题闸挡不住这些：列表页标题里"公开招聘教师"字样俱全，
只有正文才看得出它在公布成绩、公示拟聘名单，或者压根是机构转让广告。
新的正文级复检（services.crawler.is_recruitment_body）已经拦在入库处，
但历史数据还在库里，需要单独清一次。

删除而不是打标记：这些记录的学校名、学科都是误解析出来的垃圾，
留在库里只会继续污染岗位列表和筛选计数。原始公告仍可通过 source_url 追溯。

用法：
    python scripts/purge_non_postings.py --dry-run   # 只看会删什么
    python scripts/purge_non_postings.py             # 实际删除
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402

from database import SessionLocal  # noqa: E402
from models import Job, MatchResult  # noqa: E402
from services.crawler import is_recruitment_body  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="只列出，不删除")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        doomed = [
            j for j in db.scalars(select(Job)).all()
            if not is_recruitment_body(j.school_name, j.description)
        ]

        print(f"扫描 {db.query(Job).count()} 个岗位，判定为非招聘内容 {len(doomed)} 条：\n")
        for j in doomed:
            print(f"  {(j.school_name or '')[:26]:<28} {(j.description or '')[:46]}")
            print(f"      {j.source_url}")

        if not doomed:
            print("没有需要清理的记录。")
            return

        if args.dry_run:
            print("\n（dry-run，未删除）")
            return

        # 先删依赖它的匹配结果，避免外键悬空。
        # 这些匹配本来就是基于垃圾岗位算出来的，没有保留价值。
        job_ids = [j.id for j in doomed]
        removed_matches = db.query(MatchResult).filter(
            MatchResult.job_id.in_(job_ids)
        ).delete(synchronize_session=False)
        for j in doomed:
            db.delete(j)
        db.commit()
        print(f"\n已删除 {len(doomed)} 个岗位、{removed_matches} 条关联匹配结果。")
    finally:
        db.close()


if __name__ == "__main__":
    main()
