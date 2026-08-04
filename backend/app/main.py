"""FastAPI 엔트리포인트.

개발:   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000  (프론트는 Vite 5173, /api 프록시)
운영:   frontend/dist 를 이 앱이 직접 서빙 → 단일 포트/단일 컨테이너
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.requests import Request

from app.api import admin, auth, receipts, restaurants, stats, transactions
from app.core.config import settings

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s"
)
log = logging.getLogger("ssel")

app = FastAPI(
    title=settings.app_name,
    description="연구실 선결제(prepaid) 잔액 관리 API",
    version="1.0.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    redoc_url=None,
)

if settings.cors_origin_list:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.on_event("startup")
def _startup() -> None:
    settings.ensure_dirs()
    log.info("DB: %s", settings.sqlalchemy_url)
    if settings.ocr_enabled:
        log.info("OCR: provider=%s model=%s", settings.ocr_provider, settings.ocr_model)
    else:
        log.warning("OCR 비활성 (OCR_BASE_URL 미설정) — 영수증은 수동 입력으로만 처리됩니다.")
    if settings.environment != "development" and settings.jwt_secret.startswith("dev-only"):
        log.error("⚠️  JWT_SECRET 이 기본값입니다. 운영에서는 반드시 교체하세요.")


# ── API 라우터 ────────────────────────────────────────────────────
API = "/api"
app.include_router(auth.router, prefix=f"{API}/auth", tags=["auth"])
app.include_router(restaurants.router, prefix=f"{API}/restaurants", tags=["restaurants"])
app.include_router(receipts.router, prefix=f"{API}/receipts", tags=["receipts"])
app.include_router(transactions.router, prefix=f"{API}/transactions", tags=["transactions"])
app.include_router(stats.router, prefix=f"{API}/stats", tags=["stats"])
app.include_router(admin.router, prefix=f"{API}/admin", tags=["admin"])


@app.get(f"{API}/health", tags=["meta"])
def health() -> dict:
    return {
        "status": "ok",
        "environment": settings.environment,
        "ocr_enabled": settings.ocr_enabled,
        "low_balance_threshold": settings.low_balance_threshold,
    }


# ── 프론트엔드 정적 서빙 (빌드 결과물이 있을 때만) ─────────────────
_dist = settings.frontend_dist
if (_dist / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(request: Request, full_path: str):
        """SPA 라우팅: /api 가 아닌 경로는 index.html 로 (실제 파일이 있으면 그 파일)."""
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        candidate = (_dist / full_path).resolve()
        if full_path and candidate.is_file() and _dist.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(_dist / "index.html")
else:

    @app.get("/", include_in_schema=False)
    def dev_root() -> dict:
        return {
            "message": "프론트엔드 빌드가 없습니다. 개발 중에는 http://localhost:5173 을 사용하세요.",
            "api_docs": "/api/docs",
        }
