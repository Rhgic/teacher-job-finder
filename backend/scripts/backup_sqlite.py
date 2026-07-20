"""[已废弃] 请改用 scripts/backup_db.py。

数据库切到 MySQL 后备份逻辑统一到 backup_db.py（按 DATABASE_URL 自动分派）。
这里保留同名入口只是为了让服务器上已有的 systemd timer 继续可用，
参数原样透传，行为与 backup_db.py 完全一致。
"""
from __future__ import annotations

import sys

from backup_db import main

if __name__ == "__main__":
    print("提示：backup_sqlite.py 已废弃，请把定时任务改为 scripts/backup_db.py。", file=sys.stderr)
    raise SystemExit(main())
