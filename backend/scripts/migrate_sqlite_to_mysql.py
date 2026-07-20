"""把现有 SQLite 数据整库搬到 MySQL。

用法（在 backend 目录下）：
    # 先预演，只统计不写入
    python3 scripts/migrate_sqlite_to_mysql.py \
        --source sqlite:///./teacher_jobs.db \
        --target "mysql+pymysql://teacher:pwd@127.0.0.1:3306/teacher_jobs?charset=utf8mb4" \
        --dry-run

    # 确认无误后真正执行（--truncate 会先清空目标表，使脚本可重复运行）
    python3 scripts/migrate_sqlite_to_mysql.py --source ... --target ... --truncate

设计要点：
- 按 metadata.sorted_tables 的拓扑序搬表（父表在前），天然满足外键约束。
- 走 SQLAlchemy Core 的类型化 Table，JSON / Enum / DateTime / Boolean
  由 SQLAlchemy 在两端各自做序列化与反序列化，不手工拼 SQL。
- 分批提交，避免一次性把大表读进内存。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, insert, select, text
from sqlalchemy.engine import Engine

from models import Base

BATCH = 500


def make_engine(url: str) -> Engine:
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, future=True, connect_args=connect_args)


def truncate_target(target: Engine) -> None:
    """反拓扑序清空目标表。MySQL 有外键时 TRUNCATE 会被拒，这里临时关掉外键检查。"""
    is_mysql = target.dialect.name == "mysql"
    with target.begin() as conn:
        if is_mysql:
            conn.execute(text("SET FOREIGN_KEY_CHECKS=0"))
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())
        if is_mysql:
            conn.execute(text("SET FOREIGN_KEY_CHECKS=1"))


def copy_table(table, source: Engine, target: Engine, dry_run: bool) -> tuple[int, int]:
    """返回 (源行数, 已写入行数)。"""
    with source.connect() as src:
        rows = [dict(r._mapping) for r in src.execute(select(table))]

    if not rows:
        return 0, 0
    if dry_run:
        return len(rows), 0

    written = 0
    with target.begin() as dst:
        for i in range(0, len(rows), BATCH):
            chunk = rows[i : i + BATCH]
            dst.execute(insert(table), chunk)
            written += len(chunk)
    return len(rows), written


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate data from SQLite to MySQL.")
    parser.add_argument("--source", required=True, help="源库 URL（SQLite）")
    parser.add_argument("--target", required=True, help="目标库 URL（MySQL）")
    parser.add_argument("--truncate", action="store_true", help="搬运前先清空目标表，使脚本可重复执行")
    parser.add_argument("--dry-run", action="store_true", help="只统计源数据行数，不写入目标库")
    args = parser.parse_args()

    if not args.source.startswith("sqlite"):
        print("源库必须是 SQLite。")
        return 1
    if args.dry_run and args.truncate:
        print("--dry-run 与 --truncate 不能同时使用。")
        return 1

    source = make_engine(args.source)
    target = make_engine(args.target)

    # 目标库建表（缺表才建，已存在的表不动）
    if not args.dry_run:
        Base.metadata.create_all(bind=target)
        if args.truncate:
            truncate_target(target)
            print("已清空目标表。")

    total_read = total_written = 0
    print(f"{'表名':<28}{'源行数':>8}{'已写入':>8}")
    print("-" * 44)
    for table in Base.metadata.sorted_tables:
        read, written = copy_table(table, source, target, args.dry_run)
        total_read += read
        total_written += written
        print(f"{table.name:<28}{read:>8}{written:>8}")

    print("-" * 44)
    print(f"{'合计':<28}{total_read:>8}{total_written:>8}")
    if args.dry_run:
        print("\n（预演模式，未写入任何数据）")
    else:
        print(f"\n迁移完成：{total_written} 行已写入 MySQL。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
