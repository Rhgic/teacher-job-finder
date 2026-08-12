"""给已入库的岗位补齐 subjects（多学科）字段。

为什么单独写脚本而不放进迁移：回填要用 crawler 的识别逻辑，
而那段逻辑会随时间改进。迁移一旦执行过就固化在历史里，
把会变的应用代码写进去，日后重放迁移得到的结果会和当初不一致。

同时修正单值 subject：原实现按标准表顺序取第一个命中的学科，
"语文"恰好排第一，于是大量多学科岗位被误标成语文。改为只有在
恰好命中一个学科时才保留单值，否则置空——错标签比没标签更有害，
它会让岗位出现在不相关的筛选结果里。

用法：
    python scripts/backfill_subjects.py --dry-run   # 只看会改什么
    python scripts/backfill_subjects.py             # 实际写库
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database import SessionLocal  # noqa: E402
from models import Job  # noqa: E402
from services import taxonomy  # noqa: E402
from services.crawler import _guess_subjects  # noqa: E402
from sqlalchemy import select  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="只统计，不写库")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        jobs = db.scalars(select(Job)).all()
        stats = Counter()
        samples: list[str] = []

        for job in jobs:
            text = f"{job.school_name or ''}\n{job.description or ''}"
            found = _guess_subjects(text)
            packed = taxonomy.pack_subjects(found)
            new_single = found[0] if len(found) == 1 else None

            if packed != job.subjects or new_single != job.subject:
                stats["changed"] += 1
                if job.subject and new_single is None and len(found) > 1:
                    stats["单值被清空(多学科)"] += 1
                    if len(samples) < 5:
                        samples.append(
                            f"  {(job.school_name or '')[:20]:<22} "
                            f"{job.subject} → {found}"
                        )
                if not found:
                    stats["仍无法识别"] += 1
                if not args.dry_run:
                    job.subjects = packed
                    job.subject = new_single

            if found:
                stats["有学科"] += 1

        if not args.dry_run:
            db.commit()

        print(f"扫描 {len(jobs)} 个岗位")
        for k, v in stats.most_common():
            print(f"  {k:<20} {v}")
        if samples:
            print("\n单值被清空的样例（原先是误标）：")
            print("\n".join(samples))
        if args.dry_run:
            print("\n（dry-run，未写库）")
    finally:
        db.close()


if __name__ == "__main__":
    main()
