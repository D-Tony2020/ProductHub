from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from sqlalchemy import text

from app.api.v1 import auth, config_api, drafts, imports_api, parts, prices, quotes, skus, template, users
from app.core.db import SessionLocal
from app.core.logging import get_logger, setup_logging
from app.services.config_engine import IncompleteConfigError

setup_logging()  # 结构化 JSON 日志（LOG_LEVEL 控级，默认 INFO）；须在 app 创建前
_log = get_logger()


@asynccontextmanager
async def _lifespan(app: FastAPI):
    _log.info("producthub backend started", extra={"event": "startup"})
    yield


app = FastAPI(title="ProductHub 产品中台", version="0.1.0", lifespan=_lifespan)

# 开发期 CORS；生产由 Caddy 同源反代，收紧为实际域名
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(IncompleteConfigError)
def incomplete_config_handler(request: Request, exc: IncompleteConfigError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "detail": "配置不完整或非法，不能保存为 SKU",
            "issues": [i.model_dump() for i in exc.issues],
        },
    )


@app.get("/healthz")
def healthz() -> dict:
    """浅层存活探针：进程在就返回 ok（不查 DB）。就绪/真健康用 /readyz。"""
    return {"status": "ok"}


@app.get("/readyz")
def readyz() -> JSONResponse:
    """深度就绪探针（区别于浅层 /healthz）：探 DB 连通 + 返回 alembic 版本。
    DB 不可达时返回 503，让外部探活/部署闸门能识别"假绿"，根除"app 活着但库死了还显示绿"。"""
    try:
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
            ver = db.execute(text("SELECT version_num FROM alembic_version")).scalar()
        finally:
            db.close()
    except Exception as exc:  # noqa: BLE001 — 就绪探针须吞所有异常并转 503
        _log.error("readyz failed", extra={"event": "readyz_fail", "err": str(exc)[:200]})
        return JSONResponse(status_code=503, content={"status": "unready", "db": "fail"})
    return JSONResponse(status_code=200, content={"status": "ready", "db": "ok", "alembic": ver})


for router in (
    auth.router,
    users.router,
    template.router,
    parts.router,
    config_api.router,
    drafts.router,
    skus.router,
    prices.router,
    quotes.router,
    imports_api.router,
):
    app.include_router(router, prefix="/api/v1")
