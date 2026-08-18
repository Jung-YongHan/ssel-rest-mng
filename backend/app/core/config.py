"""애플리케이션 설정. 모든 값은 .env 또는 환경변수로 주입한다.

⚠️ 공개 저장소이므로 내부 IP·시크릿을 이 파일에 하드코딩하지 말 것.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/ 디렉터리 (이 파일: backend/app/core/config.py)
BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # 레포 루트의 .env 와 backend/.env 둘 다 지원 (뒤쪽이 우선)
        env_file=(REPO_DIR / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── 앱 ──
    app_name: str = "연구실 선결제 관리"
    environment: str = "development"
    # 공개 주소(스킴 포함). 예: https://app.example.com
    # 이 값과 다른 Host 로 들어온 브라우저 내비게이션은 여기로 307 리다이렉트된다
    # (LAN 주소로 PWA 를 설치해 버리는 사고 방지 — main.py 의 canonical_redirect).
    # 비워두면 리다이렉트하지 않는다.
    public_origin: str = ""

    # ── DB ──
    # 비어 있으면 backend/data/app.db 사용
    database_url: str = ""

    # ── 인증 ──
    jwt_secret: str = "dev-only-insecure-secret"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 30  # 30일
    cookie_name: str = "ssel_token"
    cookie_secure: bool = False
    cookie_samesite: str = "lax"
    invite_code: str = "ssel-lab"

    # 최초 관리자 (scripts/seed.py)
    admin_email: str = "admin@example.com"
    admin_password: str = "admin1234"
    admin_name: str = "관리자"

    # ── OCR ──
    ocr_provider: str = "qwen_vl"  # qwen_vl | qwen_text | disabled
    ocr_base_url: str = ""
    ocr_model: str = "Qwen3.6-27B"
    ocr_api_key: str = ""
    ocr_timeout: int = 120
    ocr_max_image_px: int = 1600
    ocr_use_guided_json: bool = False

    # ── 업로드 ──
    max_upload_mb: int = 15

    # ── 표시 ──
    low_balance_threshold: int = 30_000

    # ── CORS (개발용, 콤마 구분) ──
    cors_origins: str = ""

    # ── 경로 (env 로 덮어쓰지 않음) ──
    @property
    def data_dir(self) -> Path:
        return BACKEND_DIR / "data"

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def frontend_dist(self) -> Path:
        return REPO_DIR / "frontend" / "dist"

    @property
    def sqlalchemy_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{(self.data_dir / 'app.db').as_posix()}"

    @property
    def is_sqlite(self) -> bool:
        return self.sqlalchemy_url.startswith("sqlite")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def ocr_enabled(self) -> bool:
        return self.ocr_provider != "disabled" and bool(self.ocr_base_url)

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.upload_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
