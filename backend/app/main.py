from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1 import auth, config_api, drafts, imports_api, parts, prices, quotes, skus, template, users
from app.services.config_engine import IncompleteConfigError

app = FastAPI(title="ProductHub 产品中台", version="0.1.0")

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
    return {"status": "ok"}


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
