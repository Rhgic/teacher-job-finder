"""FastAPI 应用入口。

启动：
    pip install -r requirements.txt
    python seed.py            # 建表 + 种子数据
    uvicorn main:app --reload # 启动后访问 http://127.0.0.1:8000/docs
"""
from fastapi import FastAPI

from database import init_db
from routers import jobs, profile, rules, matches, applications, auth, crawl, meta, settings, rag

app = FastAPI(title="教师求职小程序 API", version="0.1.0")


@app.on_event("startup")
def _startup():
    # 开发期自动建表；生产请改用 Alembic 迁移，移除此调用。
    init_db()


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok"}


app.include_router(auth.router)
app.include_router(jobs.router)
app.include_router(profile.router)
app.include_router(rules.router)
app.include_router(matches.router)
app.include_router(applications.router)
app.include_router(crawl.router)
app.include_router(meta.router)
app.include_router(settings.router)
app.include_router(rag.router)
