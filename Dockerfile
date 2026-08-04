# ==============================================================
#  연구실 선결제 관리 (ssel-rest-mng) — 단일 이미지 배포
#
#  1단계: Vite 프론트엔드 빌드            → /build/dist
#  2단계: FastAPI 백엔드 + 빌드 산출물     → /app/backend, /app/frontend/dist
#
#  app/core/config.py 가 frontend_dist 를 "backend 디렉터리의 부모/frontend/dist"
#  로 계산하므로, 이미지 레이아웃은 반드시 아래 구조를 지켜야 한다.
#      /app/backend/app/core/config.py   → BACKEND_DIR=/app/backend, REPO_DIR=/app
#      /app/frontend/dist/index.html     → settings.frontend_dist
#      /app/backend/data                 → settings.data_dir (볼륨 마운트 지점)
# ==============================================================

# ── 1단계: 프론트엔드 빌드 ─────────────────────────────────────
FROM node:24-alpine AS frontend

WORKDIR /build

# 의존성 매니페스트만 먼저 복사해 레이어 캐시를 살린다.
# package-lock.json 이 없으면 npm ci 가 실패하므로 npm install 로 폴백한다.
COPY frontend/package*.json ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi

COPY frontend/ ./
RUN npm run build && test -f dist/index.html


# ── 2단계: 런타임 ──────────────────────────────────────────────
FROM python:3.13-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Asia/Seoul

WORKDIR /app/backend

# 파이썬 의존성 (requirements.txt 만 먼저 → 소스 변경 시 재설치 안 함)
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# 백엔드 소스 (.dockerignore 가 .venv / data / __pycache__ 를 제외한다)
COPY backend/ /app/backend/

# 1단계 빌드 산출물 → settings.frontend_dist
COPY --from=frontend /build/dist /app/frontend/dist

# 엔트리포인트: 마이그레이션 후 서버 기동 (새 서버가 스스로 스키마를 만든다)
RUN printf '%s\n' \
    '#!/bin/sh' \
    'set -e' \
    'echo "[entrypoint] DB 마이그레이션 실행: alembic upgrade head"' \
    'if ! alembic upgrade head; then' \
    '  echo "[entrypoint] 마이그레이션 실패 — docs/DEPLOY.md 의 트러블슈팅(마이그레이션 충돌)을 확인하세요." >&2' \
    '  exit 1' \
    'fi' \
    'echo "[entrypoint] ✅ 마이그레이션 완료. 서버를 시작합니다."' \
    'exec "$@"' \
    > /usr/local/bin/docker-entrypoint.sh \
 && chmod 0755 /usr/local/bin/docker-entrypoint.sh

# 비루트 실행. data/ 는 SQLite DB + 영수증 이미지가 쌓이는 곳이므로 소유권을 넘긴다.
# (compose 의 named volume 은 최초 생성 시 이 디렉터리의 소유권을 그대로 이어받는다)
RUN useradd --create-home --uid 10001 appuser \
 && mkdir -p /app/backend/data/uploads \
 && chown -R appuser:appuser /app/backend/data

USER appuser

EXPOSE 8000

# curl 없이 표준 라이브러리로 헬스체크 (이미지 슬림 유지)
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips=*"]
