"""数据库备份：按 DATABASE_URL 自动分派 SQLite / MySQL。

用法：
    python3 scripts/backup_db.py                    # 读环境变量 DATABASE_URL
    python3 scripts/backup_db.py --keep 14          # 只保留最近 14 份

MySQL 走 mysqldump：
- --single-transaction 让 InnoDB 拿一致性快照，不锁表，线上可直接跑。
- 密码通过 MYSQL_PWD 环境变量传给子进程，不进命令行参数，
  避免同机器上任何用户用 ps 就能看到数据库密码。
"""
from __future__ import annotations

import argparse
import gzip
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BACKUP_SUFFIXES = ("*.sqlite3", "*.sql.gz")


def sqlite_path_from_url(database_url: str) -> Path:
    raw = database_url.split(":///", 1)[-1] if ":///" in database_url else database_url.removeprefix("sqlite://")
    parsed = urlparse(raw)
    value = parsed.path if parsed.scheme else raw
    path = Path(unquote(value))
    return path if path.is_absolute() else Path.cwd() / path


def backup_sqlite(database_url: str, output_dir: Path) -> Path:
    source = sqlite_path_from_url(database_url)
    if not source.exists():
        raise FileNotFoundError(f"数据库文件不存在：{source}")
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = output_dir / f"{source.stem}-{stamp}.sqlite3"
    # sqlite3 的在线备份 API，读写并发时也能拿到一致快照
    with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
        src.backup(dst)
    return target


def backup_mysql(database_url: str, output_dir: Path) -> Path:
    from sqlalchemy.engine import make_url

    if shutil.which("mysqldump") is None:
        raise RuntimeError("未找到 mysqldump，请先安装 MySQL 客户端工具（mysql-client）。")

    url = make_url(database_url)
    if not url.database:
        raise ValueError("DATABASE_URL 里缺少数据库名。")

    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = output_dir / f"{url.database}-{stamp}.sql.gz"

    cmd = [
        "mysqldump",
        f"--host={url.host or '127.0.0.1'}",
        f"--port={url.port or 3306}",
        f"--user={url.username or 'root'}",
        "--single-transaction",   # InnoDB 一致性快照，不锁表
        "--routines",
        "--triggers",
        "--events",
        "--default-character-set=utf8mb4",
        url.database,
    ]

    env = os.environ.copy()
    if url.password:
        env["MYSQL_PWD"] = url.password  # 不放命令行，避免 ps 泄露

    # 注意：不能把 gzip 文件对象直接交给 subprocess 的 stdout——子进程写的是它的
    # 底层 fd，会绕过 gzip 压缩层，产出一个顶着 .gz 名字的裸 SQL 文件。
    # 这里显式把子进程输出流式喂给 gzip，边导边压，大库也不占内存。
    # stderr 写临时文件而非 PIPE：避免管道缓冲区写满导致死锁。
    with tempfile.TemporaryFile() as err_file:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=err_file, env=env)
        try:
            with gzip.open(target, "wb") as fh:
                shutil.copyfileobj(proc.stdout, fh)
        finally:
            proc.stdout.close()
        returncode = proc.wait()
        if returncode != 0:
            err_file.seek(0)
            message = err_file.read().decode("utf-8", "replace").strip()
            target.unlink(missing_ok=True)
            raise RuntimeError(f"mysqldump 失败：{message}")
    return target


def prune(output_dir: Path, keep: int) -> list[Path]:
    if keep <= 0:
        return []
    backups: list[Path] = []
    for pattern in BACKUP_SUFFIXES:
        backups.extend(output_dir.glob(pattern))
    backups.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    removed: list[Path] = []
    for old in backups[keep:]:
        old.unlink()
        removed.append(old)
    return removed


def main() -> int:
    parser = argparse.ArgumentParser(description="Backup the application database (SQLite or MySQL).")
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL", "sqlite:///./teacher_jobs.db"))
    parser.add_argument("--output-dir", default=os.getenv("BACKUP_DIR", "./backups"))
    parser.add_argument("--keep", type=int, default=int(os.getenv("BACKUP_KEEP", "14")))
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    try:
        if args.database_url.startswith("sqlite"):
            target = backup_sqlite(args.database_url, output_dir)
        elif args.database_url.startswith("mysql"):
            target = backup_mysql(args.database_url, output_dir)
        else:
            raise ValueError(f"暂不支持的数据库类型：{args.database_url.split(':', 1)[0]}")
        removed = prune(output_dir, args.keep)
    except Exception as exc:  # noqa: BLE001 - CLI should report plain error.
        print(f"备份失败：{exc}")
        return 1

    size_mb = target.stat().st_size / 1024 / 1024
    print(f"备份完成：{target}（{size_mb:.2f} MB）")
    if removed:
        print(f"已清理旧备份：{len(removed)} 个")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
