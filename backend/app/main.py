"""FastAPI 엔트리포인트.

개발:   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000  (프론트는 Vite 5173, /api 프록시)
운영:   frontend/dist 를 이 앱이 직접 서빙 → 단일 포트/단일 컨테이너
"""

from __future__ import annotations

import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.requests import Request
from starlette.responses import Response

from app.api import admin, auth, receipts, restaurants, stats, transactions
from app.core.config import settings

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s"
)
log = logging.getLogger("ssel")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings.ensure_dirs()
    log.info("DB: %s", settings.sqlalchemy_url)
    if settings.ocr_enabled:
        log.info("OCR: provider=%s model=%s", settings.ocr_provider, settings.ocr_model)
    else:
        log.warning("OCR 비활성 (OCR_BASE_URL 미설정) — 영수증은 수동 입력으로만 처리됩니다.")
    if settings.environment != "development":
        if settings.jwt_secret.startswith("dev-only"):
            log.error("⚠️  JWT_SECRET 이 기본값입니다. 운영에서는 반드시 교체하세요.")
        if settings.invite_code == "ssel-lab":
            log.error("⚠️  INVITE_CODE 가 기본값입니다. 누구나 가입할 수 있습니다.")
    if settings.public_origin:
        # 형식이 틀리면 리다이렉트가 조용히 안 걸리므로 기동 때 알려준다.
        parsed = urlsplit(settings.public_origin.strip().rstrip("/"))
        if not parsed.scheme or not parsed.netloc:
            log.error(
                "⚠️  PUBLIC_ORIGIN 형식이 올바르지 않습니다(스킴 포함 필요): %r — 무시합니다.",
                settings.public_origin,
            )
        else:
            log.info("정규 주소: %s (다른 Host 의 화면 요청은 이쪽으로 보냅니다)", settings.public_origin)
    yield


app = FastAPI(
    title=settings.app_name,
    description="연구실 선결제(prepaid) 잔액 관리 API",
    version="1.0.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    redoc_url=None,
    lifespan=lifespan,
)

if settings.cors_origin_list:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


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


# ── 정적 파일 캐시 정책 ────────────────────────────────────────────
#
# 왜 파일마다 다르게 주는가:
#   `assets/` 아래 파일은 이름에 내용 해시가 박혀 있어 내용이 바뀌면 URL 이 바뀐다
#   → 영구 캐시가 안전하다. 반대로 셸(index.html·sw.js·manifest)은 URL 이 고정이라
#   매 요청 재검증해야 한다.
#
#   Cache-Control 을 **아예 주지 않으면** 브라우저가 휴리스틱 캐싱으로 옛 셸을
#   재검증 없이 계속 쓴다. 그 셸은 이미 사라진 청크 해시를 가리키므로 앱이 통째로
#   뜨지 않는다 (iOS 홈 화면 웹앱에서 실제로 겪었다). 셸은 4~6KB 라 매번 받아도
#   싸다 — 캐시 이득보다 옛 셸에 갇히지 않는 쪽이 훨씬 중요하다.
CACHE_IMMUTABLE = "public, max-age=31536000, immutable"
CACHE_REVALIDATE = "no-cache"
# 아이콘·favicon 처럼 URL 이 고정이지만 자주 바뀌지 않는 나머지 파일.
# 휴리스틱 캐싱에 맡기면 며칠씩 붙잡히므로 짧게 못 박는다.
# (그림을 바꿀 때는 vite.config.ts 주석대로 파일명에 -vN 을 올린다)
CACHE_SHORT = "public, max-age=3600"

# URL 이 고정인 셸 파일들
SHELL_FILES = frozenset({"index.html", "sw.js", "manifest.webmanifest", "registerSW.js"})
# 루트에 있지만 파일명에 내용 해시가 있는 것 (vite-plugin-pwa 의 workbox 런타임)
_HASHED_ROOT_FILE = re.compile(r"^workbox-[0-9a-f]{8}\.js$")


def cache_control_for(filename: str) -> str:
    """dist 루트의 파일 하나에 줄 `Cache-Control` 값."""
    if filename in SHELL_FILES:
        return CACHE_REVALIDATE
    if _HASHED_ROOT_FILE.match(filename):
        return CACHE_IMMUTABLE
    return CACHE_SHORT


class HashedAssets(StaticFiles):
    """`assets/` 전용 마운트 — 해시 파일명이므로 영구 캐시로 내려준다.

    StaticFiles 는 Cache-Control 을 붙이지 않으므로 여기서 얹는다.
    """

    def file_response(self, *args: Any, **kwargs: Any) -> Response:
        response = super().file_response(*args, **kwargs)
        response.headers["cache-control"] = CACHE_IMMUTABLE
        return response


def canonical_redirect(request: Request, full_path: str) -> RedirectResponse | None:
    """정규 주소가 아닌 Host 로 들어온 **브라우저 내비게이션**을 `PUBLIC_ORIGIN` 으로 보낸다.

    LAN 주소(`http://<노드IP>:8000`)로 홈 화면에 추가한 PWA 는 사내망을 벗어나면
    어떤 요청도 서버에 닿지 않는데, 서비스워커가 셸을 캐시에서 띄워 주기 때문에
    화면은 멀쩡히 뜬다 → "로그인만 안 되는 앱" 으로 보인다(실제로 겪은 사고).
    게다가 평문 HTTP 에서는 `COOKIE_SECURE=true` 쿠키가 저장되지 않아 그 주소로는
    애초에 로그인을 끝낼 수 없다. 잘못된 주소로 설치·북마크되는 길을 막는다.

    옮기는 것은 **내비게이션뿐**이다. XHR·정적 파일을 크로스오리진으로 돌리면
    CORS 로 조용히 실패하고 서비스워커 프리캐시도 깨진다.

    영구(308)가 아니라 임시(307)를 쓴다 — `PUBLIC_ORIGIN` 을 잘못 넣었을 때
    브라우저 캐시에 박혀 되돌릴 수 없게 되는 편이 더 위험하다.
    """
    origin = settings.public_origin.strip().rstrip("/")
    if not origin:
        return None

    parsed = urlsplit(origin)
    if not parsed.scheme or not parsed.netloc:
        # 잘못 넣은 값 때문에 서비스가 멈추지는 않게 한다 (기동 로그에 경고를 남긴다)
        return None

    host = request.headers.get("host", "")
    if host == parsed.netloc:
        return None
    # 서버에서 직접 확인할 때(healthcheck·SSH 포트포워딩)는 방해하지 않는다
    if host.split(":")[0].strip("[]") in {"localhost", "127.0.0.1", "::1"}:
        return None

    # 문서 요청만 옮긴다. Sec-Fetch-Mode 를 안 보내는 클라이언트는 Accept 로 판단한다.
    navigation = (
        request.headers.get("sec-fetch-mode") == "navigate"
        or "text/html" in request.headers.get("accept", "")
    )
    if not navigation:
        return None

    query = request.url.query
    target = f"{origin}/{full_path}" + (f"?{query}" if query else "")
    return RedirectResponse(target, status_code=307)


def mount_frontend(app: FastAPI, dist: Path) -> None:
    """빌드된 프론트엔드(dist)를 앱에 붙인다.

    실제 `frontend/dist` 없이도(=CI) 캐시 헤더·리다이렉트를 검증할 수 있도록
    함수로 분리해 두었다. **`/api` 라우터를 모두 등록한 뒤** 호출해야 한다 —
    아래 catch-all 이 나머지 경로를 전부 삼킨다.
    """
    if (dist / "assets").is_dir():
        app.mount("/assets", HashedAssets(directory=dist / "assets"), name="assets")

    root = dist.resolve()

    # HEAD 도 받는다. FastAPI 의 @app.get 은 HEAD 를 자동으로 붙이지 않아
    # 405 가 나가는데, 아이콘·정적 파일의 존재를 HEAD 로 먼저 확인하는
    # 클라이언트가 있다.
    @app.api_route("/{full_path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    def spa_fallback(request: Request, full_path: str) -> Response:
        """SPA 라우팅: /api 가 아닌 경로는 index.html 로 (실제 파일이 있으면 그 파일)."""
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)

        redirect = canonical_redirect(request, full_path)
        if redirect is not None:
            return redirect

        # 경로 탈출(../) 방어: resolve 후 dist 안쪽인지 확인
        candidate = (root / full_path).resolve()
        if full_path and candidate.is_file() and root in candidate.parents:
            return FileResponse(
                candidate, headers={"cache-control": cache_control_for(candidate.name)}
            )
        # SPA 라우트에는 확장자가 없다(/login, /restaurants/3). 확장자가 있는데
        # 파일이 없으면 없는 정적 파일이므로 404 를 준다.
        #
        # index.html 을 200 으로 돌려주면 클라이언트가 그 HTML 을 이미지·스크립트로
        # 디코딩하려다 실패한다. 실제로 iOS 가 홈 화면 추가 때 관례 경로인
        # /apple-touch-icon-precomposed.png 를 먼저 찾는데, 여기서 200 + HTML 을
        # 받고 "아이콘은 있는데 깨졌다"로 판단해 아이콘 대신 글자 타일을 만들었다.
        if PurePosixPath(full_path).suffix:
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        return FileResponse(root / "index.html", headers={"cache-control": CACHE_REVALIDATE})


# ── 프론트엔드 정적 서빙 (빌드 결과물이 있을 때만) ─────────────────
_dist = settings.frontend_dist
if (_dist / "index.html").exists():
    mount_frontend(app, _dist)
else:

    @app.get("/", include_in_schema=False)
    def dev_root() -> dict:
        return {
            "message": "프론트엔드 빌드가 없습니다. 개발 중에는 http://localhost:5173 을 사용하세요.",
            "api_docs": "/api/docs",
        }
