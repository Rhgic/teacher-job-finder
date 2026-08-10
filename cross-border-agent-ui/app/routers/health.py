"""健康检查。

只回服务与数据库可用状态。刻意不回环境变量、密钥是否配置、版本路径等信息——
健康检查通常是唯一免鉴权的端点，泄露面要压到最小。
"""

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health(db: Session = Depends(get_db)) -> dict:
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:  # noqa: BLE001 — 健康检查不该因为探测失败而 500
        db_ok = False
    return {"status": "ok" if db_ok else "degraded", "database": "up" if db_ok else "down"}
