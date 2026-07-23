"""备份恢复演练：把最近一份备份真的恢复到临时库并比对。

**没演练过的备份等于没有备份。** 备份脚本跑得再规律，
如果从没验证过"能不能恢复回来"，那只是在定时产出一堆没用过的文件。

这个脚本只往临时库写，全程不碰生产库，跑完自动清理。

用法：
    python3 scripts/verify_backup_restore.py
    python3 scripts/verify_backup_restore.py --keep-temp   # 保留临时库便于排查
"""
from __future__ import annotations

import argparse
import gzip
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TEMP_DB = "teacher_jobs_restore_drill"


def load_env(path: Path) -> dict:
    env = {}
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def parse_mysql_url(url: str) -> dict:
    parts = urlsplit(url)
    return {
        "host": parts.hostname or "127.0.0.1",
        "port": str(parts.port or 3306),
        "user": unquote(parts.username or ""),
        "password": unquote(parts.password or ""),
        "database": (parts.path or "/").lstrip("/").split("?")[0],
    }


def mysql_cmd(conf: dict, database: str | None = None) -> list[str]:
    cmd = ["mysql", f"-h{conf['host']}", f"-P{conf['port']}", f"-u{conf['user']}"]
    if database:
        cmd.append(database)
    return cmd


def run_sql(conf: dict, sql: str, database: str | None = None) -> str:
    """密码走 MYSQL_PWD 环境变量，不进命令行，避免在 ps 里泄露。"""
    env = {**os.environ, "MYSQL_PWD": conf["password"]}
    proc = subprocess.run(
        mysql_cmd(conf, database) + ["-N", "-B", "-e", sql],
        capture_output=True, text=True, env=env,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip()[:300])
    return proc.stdout.strip()


def table_counts(conf: dict, database: str) -> dict[str, int]:
    rows = run_sql(conf, (
        "SELECT table_name, table_rows FROM information_schema.tables "
        f"WHERE table_schema='{database}' AND table_name!='alembic_version'"
    ))
    # information_schema.table_rows 对 InnoDB 是估算值，只用来看表是否存在；
    # 真实行数下面逐表 COUNT(*)。
    names = [r.split("\t")[0] for r in rows.splitlines() if r.strip()]
    counts = {}
    for name in names:
        counts[name] = int(run_sql(conf, f"SELECT COUNT(*) FROM `{name}`", database) or 0)
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description="Backup restore drill.")
    parser.add_argument("--keep-temp", action="store_true", help="演练后保留临时库")
    args = parser.parse_args()

    env = load_env(ROOT / ".env")
    url = env.get("DATABASE_URL", "")
    if not url.startswith("mysql"):
        print("✗ DATABASE_URL 不是 MySQL，本脚本只演练 MySQL 备份")
        return 1

    # 缺客户端时给出可操作提示，而不是抛一串 FileNotFoundError 堆栈。
    # 数据库跑在 Docker 里时宿主机常常没装 mysql 客户端。
    if shutil.which("mysql") is None:
        print("✗ 找不到 mysql 客户端。二选一：")
        print("    apt-get install -y mysql-client")
        print("    或在容器里跑：docker exec -i teacher-jobs-mysql mysql ...")
        return 1

    conf = parse_mysql_url(url)
    prod_db = conf["database"]

    # 建库/删库是管理操作，应用账号本就不该有这个权限（实测服务器上
    # teacher 账号确实被拒，这是正确的最小权限配置，不是配置错误）。
    # 因此演练用 root 连接，只在临时库上操作。
    root_pwd = env.get("MYSQL_ROOT_PASSWORD", "")
    if not root_pwd:
        print("✗ .env 里没有 MYSQL_ROOT_PASSWORD")
        print("  演练需要建临时库，应用账号没有建库权限（这是对的）")
        return 1
    admin = {**conf, "user": "root", "password": root_pwd}
    backup_dir = Path(env.get("BACKUP_DIR", "./backups"))
    if not backup_dir.is_absolute():
        backup_dir = (ROOT / backup_dir).resolve()

    print("备份恢复演练")
    print(f"  生产库 {prod_db}    备份目录 {backup_dir}")

    # 1) 找最近一份备份
    backups = sorted(backup_dir.glob("*.sql.gz"), key=lambda p: p.stat().st_mtime)
    if not backups:
        print(f"✗ {backup_dir} 下没有 *.sql.gz —— 备份可能从未成功产出过")
        return 1
    latest = backups[-1]
    age_h = (time.time() - latest.stat().st_mtime) / 3600
    size_mb = latest.stat().st_size / 1024 / 1024
    print(f"\n[1/5] 最近备份 {latest.name}")
    print(f"      大小 {size_mb:.2f} MB    产出于 {age_h:.1f} 小时前    共 {len(backups)} 份")
    if latest.stat().st_size == 0:
        print("✗ 备份文件是空的")
        return 1

    # 2) 验证是真 gzip 而非顶着 .gz 名字的裸文件
    #    这是本项目踩过的真坑：把 gzip 文件对象直接交给 subprocess 的 stdout，
    #    子进程写的是底层 fd、绕过压缩层，产出的文件解不开。
    print("\n[2/5] 校验压缩完整性")
    try:
        with gzip.open(latest, "rb") as fh:
            head = fh.read(4096)
            raw = 0
            while chunk := fh.read(1 << 20):
                raw += len(chunk)
    except OSError as exc:
        print(f"✗ 不是有效的 gzip：{exc}")
        print("  很可能是假压缩（顶着 .gz 名字的裸 SQL），备份不可用")
        return 1
    if b"CREATE TABLE" not in head and b"MySQL dump" not in head:
        print("✗ 解开后不像 mysqldump 产物")
        return 1
    print(f"      ✓ 真 gzip，解压后约 {(raw + len(head)) / 1024 / 1024:.2f} MB")

    # 3) 建临时库
    print(f"\n[3/5] 建临时库 {TEMP_DB}")
    run_sql(admin, f"DROP DATABASE IF EXISTS `{TEMP_DB}`")
    run_sql(admin, f"CREATE DATABASE `{TEMP_DB}` "
                  "CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci")

    # 4) 恢复并计时（RTO）
    print("\n[4/5] 恢复中…")
    started = time.perf_counter()
    env_pwd = {**os.environ, "MYSQL_PWD": admin["password"]}
    with gzip.open(latest, "rb") as fh:
        proc = subprocess.run(mysql_cmd(admin, TEMP_DB), stdin=fh,
                              capture_output=True, env=env_pwd)
    rto = time.perf_counter() - started
    if proc.returncode != 0:
        print(f"✗ 恢复失败：{proc.stderr.decode()[:300]}")
        return 1
    print(f"      ✓ 恢复完成，耗时 {rto:.1f} 秒（RTO）")

    # 5) 比对生产库与恢复库
    print("\n[5/5] 比对表与行数")
    prod = table_counts(admin, prod_db)
    restored = table_counts(admin, TEMP_DB)

    only_prod = set(prod) - set(restored)
    only_restored = set(restored) - set(prod)
    diff = {t: (prod[t], restored[t]) for t in set(prod) & set(restored)
            if prod[t] != restored[t]}

    print(f"      生产库 {len(prod)} 表 / {sum(prod.values())} 行")
    print(f"      恢复库 {len(restored)} 表 / {sum(restored.values())} 行")

    ok = True
    if only_prod:
        print(f"      ✗ 备份里缺失的表：{sorted(only_prod)}")
        ok = False
    if only_restored:
        print(f"      ! 恢复库多出的表：{sorted(only_restored)}")
    if diff:
        # 备份是某个时间点的快照，之后生产库继续写入属正常，
        # 只要恢复库不多于生产库即可。
        grew = {t: v for t, v in diff.items() if v[1] > v[0]}
        for t, (p, r) in sorted(diff.items()):
            mark = "✗" if t in grew else "·"
            print(f"      {mark} {t}: 生产 {p} → 恢复 {r}"
                  f"{'（恢复库反而更多，异常）' if t in grew else '（备份后生产库有新增，正常）'}")
        if grew:
            ok = False

    if not args.keep_temp:
        run_sql(admin, f"DROP DATABASE IF EXISTS `{TEMP_DB}`")
        print(f"\n      已清理临时库 {TEMP_DB}")
    else:
        print(f"\n      临时库 {TEMP_DB} 已保留")

    print("\n" + ("✓ 演练通过：这份备份能真正恢复回来" if ok
                  else "✗ 演练未通过，备份不可信，请先修复备份流程"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
