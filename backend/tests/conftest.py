"""테스트 공용 설정.

⚠️ **순서가 중요하다.** `app.core.db` 는 import 시점에 `settings.sqlalchemy_url` 로
   엔진을 만들어 버리기 때문에, 이 모듈 최상단에서 `app.*` 를 건드리기 **전에**
   환경변수를 먼저 세팅해야 한다. 그래야 개발자 로컬 DB 를 절대 건드리지 않는다.

스키마는 Alembic 이 아니라 `Base.metadata.create_all()` 로 만든다
(마이그레이션 에이전트 작업과 테스트를 분리하기 위함).

테스트 격리: 매 테스트 시작 전에 모든 테이블을 비운다.
"""

from __future__ import annotations

import io
import os
import shutil
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

# ══════════════════════════════════════════════════════════════════
#  1) app 모듈을 import 하기 전에 환경을 완전히 격리한다
# ══════════════════════════════════════════════════════════════════
_TMP_ROOT = Path(tempfile.mkdtemp(prefix="ssel-pytest-"))
_DB_PATH = _TMP_ROOT / "test.db"

# DATABASE_URL 은 반드시 임시 파일. (환경변수가 .env 보다 우선하므로
# 개발자 로컬 .env 가 무엇이든 테스트는 이 값을 쓴다)
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_PATH.as_posix()}"
# 테스트 실행 표시 + 임시 루트 경로 노출
os.environ["PYTEST"] = str(_TMP_ROOT)

# 기대값이 로컬 .env 에 흔들리지 않도록 **강제로** 덮어쓴다.
os.environ["ENVIRONMENT"] = "test"
os.environ["JWT_SECRET"] = "pytest-only-secret-not-for-production"
os.environ["JWT_EXPIRE_MINUTES"] = "60"
os.environ["COOKIE_SECURE"] = "false"
os.environ["INVITE_CODE"] = "pytest-invite-code"
os.environ["ADMIN_EMAIL"] = "seed-admin@test.local"
os.environ["ADMIN_PASSWORD"] = "seedadmin1234"
os.environ["ADMIN_NAME"] = "시드관리자"
os.environ["OCR_PROVIDER"] = "disabled"  # 테스트가 절대 네트워크를 타지 않게
os.environ["OCR_BASE_URL"] = ""
os.environ["OCR_API_KEY"] = ""
os.environ["MAX_UPLOAD_MB"] = "15"
os.environ["LOW_BALANCE_THRESHOLD"] = "30000"
os.environ["CORS_ORIGINS"] = ""

# `settings.data_dir` / `upload_dir` 은 BACKEND_DIR 전역을 **호출 시점에** 읽는
# property 이므로, 전역을 임시 경로로 갈아끼우면 업로드 파일도 tmp 로 간다.
# (덕분에 테스트가 backend/data/ 를 오염시키지 않는다)
from app.core import config as _config  # noqa: E402

_config.BACKEND_DIR = _TMP_ROOT
_config.settings.ensure_dirs()

INVITE_CODE = os.environ["INVITE_CODE"]
LOW_BALANCE_THRESHOLD = int(os.environ["LOW_BALANCE_THRESHOLD"])

# ══════════════════════════════════════════════════════════════════
#  2) 이제 안전하게 app 을 import 하고 스키마를 만든다
# ══════════════════════════════════════════════════════════════════
from app.core.config import settings  # noqa: E402
from app.core.db import Base, SessionLocal, engine  # noqa: E402
from app.core.timeutil import to_utc_naive, utc_now  # noqa: E402
from app.models import (  # noqa: E402
    Receipt,
    Restaurant,
    Transaction,
    TxType,
    User,
)

assert settings.sqlalchemy_url.endswith("test.db"), (
    f"테스트가 임시 DB 를 쓰지 않고 있습니다: {settings.sqlalchemy_url}"
)

Base.metadata.create_all(engine)

PARSED_KEYS = (
    "store_name",
    "business_number",
    "address",
    "phone",
    "total_amount",
    "paid_at",
)

# 테스트용 계정 (첫 가입자가 admin 이 되는 규약 때문에 순서가 중요하다)
ADMIN_CREDS = {"email": "admin@test.local", "name": "관리자", "password": "adminpass1234"}
MEMBER_CREDS = {"email": "member@test.local", "name": "구성원", "password": "memberpass1234"}


# ══════════════════════════════════════════════════════════════════
#  세션 정리
# ══════════════════════════════════════════════════════════════════
@pytest.fixture(scope="session", autouse=True)
def _session_teardown():
    yield
    engine.dispose()
    # Windows 에서 SQLite WAL 파일이 잠겨 있을 수 있으므로 실패를 무시한다
    shutil.rmtree(_TMP_ROOT, ignore_errors=True)


# ══════════════════════════════════════════════════════════════════
#  테스트 격리 — 매 테스트 전에 전체 테이블 비우기
# ══════════════════════════════════════════════════════════════════
def _truncate_all() -> None:
    with engine.begin() as conn:
        # FK 의존 역순으로 삭제 (transactions → receipts/restaurants → users)
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())


@pytest.fixture(autouse=True)
def _clean_db():
    """매 테스트 **시작 전** 초기화. 앞선 테스트가 실패해도 다음 테스트는 깨끗하다."""
    _truncate_all()
    yield


# ══════════════════════════════════════════════════════════════════
#  DB 세션
# ══════════════════════════════════════════════════════════════════
@pytest.fixture
def db(_clean_db):
    """직접 ORM 을 만질 때 쓰는 세션.

    앱은 요청마다 자기 세션을 쓰므로, 팩토리는 **반드시 commit** 해서
    앱 쪽에서도 보이게 만든다.
    """
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


# ══════════════════════════════════════════════════════════════════
#  FastAPI 앱 / 클라이언트
# ══════════════════════════════════════════════════════════════════
@pytest.fixture(scope="session")
def app_instance():
    """`app.main:app`.

    병렬 작업 중에는 라우터 모듈이 아직 없을 수 있다. 그 경우에는
    **collection 에러가 아니라 skip** 으로 명확히 구분되게 만든다.
    (그 외의 import 실패는 진짜 버그이므로 그대로 터뜨린다)
    """
    try:
        from app.main import app
    except ModuleNotFoundError as exc:  # pragma: no cover - 병렬 작업 과도기
        missing = exc.name or ""
        if missing.startswith(("app.api", "app.schemas", "app.services")):
            pytest.skip(f"백엔드 API 모듈이 아직 없습니다: {missing}")
        raise
    return app


@pytest.fixture
def client(app_instance, _clean_db):
    """비인증 클라이언트 (쿠키 없음)."""
    from fastapi.testclient import TestClient

    with TestClient(app_instance) as c:
        yield c


def _register(client, creds: dict) -> dict:
    resp = client.post("/api/auth/register", json={**creds, "invite_code": INVITE_CODE})
    assert resp.status_code == 201, f"가입 실패: {resp.status_code} {resp.text}"
    return resp.json()


@pytest.fixture
def admin_client(app_instance, _clean_db):
    """실제 `/api/auth/register` 로 가입한 관리자 (쿠키가 실제로 오간다).

    규약상 **첫 번째 가입자가 자동 admin** 이므로 이 fixture 가 먼저 가입한다.
    """
    from fastapi.testclient import TestClient

    with TestClient(app_instance) as c:
        user = _register(c, ADMIN_CREDS)
        assert user["role"] == "admin", "첫 가입자는 자동으로 admin 이어야 한다"
        c.user = user
        yield c


@pytest.fixture
def member_client(app_instance, admin_client):
    """일반 구성원 클라이언트.

    `admin_client` 에 의존한다 — 관리자가 먼저 존재해야 이 계정이 member 가 된다.
    """
    from fastapi.testclient import TestClient

    with TestClient(app_instance) as c:
        user = _register(c, MEMBER_CREDS)
        assert user["role"] == "member"
        c.user = user
        yield c


@pytest.fixture
def invite_code() -> str:
    return INVITE_CODE


@pytest.fixture
def register():
    """가입 요청 헬퍼 — 실패 케이스도 검사할 수 있게 Response 를 그대로 준다."""

    def _do(
        client,
        *,
        email: str = "someone@test.local",
        name: str = "누군가",
        password: str = "password1234",
        invite_code: str = INVITE_CODE,
        **extra,
    ):
        payload = {
            "email": email,
            "name": name,
            "password": password,
            "invite_code": invite_code,
        }
        payload.update(extra)
        return client.post("/api/auth/register", json=payload)

    return _do


# ══════════════════════════════════════════════════════════════════
#  데이터 팩토리
# ══════════════════════════════════════════════════════════════════
@pytest.fixture
def make_restaurant(db):
    """식당 생성 팩토리 (commit 까지 수행)."""
    counter = {"n": 0}

    def _make(
        name: str | None = None,
        *,
        business_number: str | None = None,
        address: str | None = None,
        phone: str | None = None,
        memo: str | None = None,
        is_archived: bool = False,
        created_by: int | None = None,
    ) -> Restaurant:
        counter["n"] += 1
        if name is None:
            name = f"테스트식당{counter['n']}"
        if business_number is not None:
            # 저장은 항상 숫자 10자리 정규화 형태 (§0)
            business_number = "".join(ch for ch in str(business_number) if ch.isdigit())
        restaurant = Restaurant(
            name=name,
            business_number=business_number,
            address=address,
            phone=phone,
            memo=memo,
            is_archived=is_archived,
            created_by=created_by,
        )
        db.add(restaurant)
        db.commit()
        db.refresh(restaurant)
        return restaurant

    return _make


@pytest.fixture
def make_tx(db):
    """거래 생성 팩토리.

    잔액 검증을 우회해 원장을 직접 만든다 (경계 상황 세팅용).
    음수 잔액이나 void 된 거래를 손쉽게 심을 수 있다.
    """

    def _make(
        restaurant,
        tx_type: str | TxType = TxType.CHARGE,
        amount: int = 10_000,
        *,
        occurred_at=None,
        days_ago: int | None = None,
        memo: str | None = None,
        created_by: int | None = None,
        receipt_id: int | None = None,
        voided: bool = False,
        void_reason: str | None = None,
        voided_by: int | None = None,
    ) -> Transaction:
        restaurant_id = restaurant if isinstance(restaurant, int) else restaurant.id
        if isinstance(tx_type, str):
            tx_type = TxType(tx_type)
        if occurred_at is None:
            occurred_at = utc_now()
            if days_ago:
                occurred_at = occurred_at - timedelta(days=days_ago)

        tx = Transaction(
            restaurant_id=restaurant_id,
            type=tx_type,
            amount=amount,
            occurred_at=occurred_at,
            memo=memo,
            receipt_id=receipt_id,
            created_by=created_by,
        )
        if voided:
            tx.voided_at = utc_now()
            tx.void_reason = void_reason or "테스트 취소"
            tx.voided_by = voided_by
        db.add(tx)
        db.commit()
        db.refresh(tx)
        return tx

    return _make


# ══════════════════════════════════════════════════════════════════
#  영수증 / OCR
# ══════════════════════════════════════════════════════════════════
@pytest.fixture
def jpeg_bytes():
    """테스트용 작은 JPEG 를 즉석에서 만든다 (고정 바이너리 파일을 커밋하지 않기 위해)."""

    def _make(width: int = 320, height: int = 480, color=(248, 248, 248)) -> bytes:
        from PIL import Image, ImageDraw

        image = Image.new("RGB", (width, height), color)
        draw = ImageDraw.Draw(image)
        draw.rectangle([8, 8, width - 8, height - 8], outline=(40, 40, 40), width=2)
        draw.line([8, 60, width - 8, 60], fill=(40, 40, 40), width=1)
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=85)
        return buffer.getvalue()

    return _make


@pytest.fixture
def stub_ocr(monkeypatch):
    """OCR provider 를 오프라인 스텁으로 고정한다.

    기본값은 "전부 None" (= DisabledProvider 와 동일). 테스트에서
    `stub_ocr({"store_name": "...", ...})` 로 원하는 파싱 결과를 주입할 수 있다.
    반드시 이 fixture 를 써서 네트워크 호출 가능성을 0 으로 만든다.
    """
    from app.services import ocr as ocr_module

    result_cls = getattr(ocr_module, "OcrResult", None)
    # 계약상 OcrResult.parsed["paid_at"] 은 **naive UTC datetime** 이다 (문자열이 아니다).
    # 테스트에서는 편의상 문자열로 적을 수 있게 여기서 변환한다.
    parse_dt = getattr(ocr_module, "parse_datetime", None)

    def _coerce_paid_at(value):
        if value is None or isinstance(value, datetime):
            return value
        if parse_dt is not None:
            return parse_dt(value)
        return to_utc_naive(datetime.fromisoformat(str(value)))

    def _install(parsed: dict | None = None, *, error=None, raw=None, elapsed_ms: int = 1):
        payload = dict.fromkeys(PARSED_KEYS)
        payload.update(parsed or {})
        payload["paid_at"] = _coerce_paid_at(payload["paid_at"])

        def _build():
            kwargs = {
                "parsed": dict(payload),
                "raw": raw,
                "elapsed_ms": elapsed_ms,
                "error": error,
            }
            if result_cls is not None:
                return result_cls(**kwargs)
            return SimpleNamespace(**kwargs)

        class _StubProvider:
            def extract(self, image_path):  # noqa: ARG002 - 인터페이스 유지
                return _build()

        provider = _StubProvider()
        monkeypatch.setattr(ocr_module, "get_ocr_provider", lambda: provider, raising=False)
        # 라우터가 이름을 직접 import 한 경우도 대비
        try:
            from app.api import receipts as receipts_module
        except ImportError:  # pragma: no cover
            pass
        else:
            if hasattr(receipts_module, "get_ocr_provider"):
                monkeypatch.setattr(
                    receipts_module, "get_ocr_provider", lambda: provider, raising=False
                )
        return provider

    _install()  # 기본 설치: 전부 None
    return _install


@pytest.fixture
def upload_receipt(jpeg_bytes):
    """영수증 업로드 헬퍼. `stub_ocr` 과 함께 쓸 것."""

    def _upload(client, *, filename: str = "receipt.jpg", content_type: str = "image/jpeg"):
        return client.post(
            "/api/receipts",
            files={"file": (filename, jpeg_bytes(), content_type)},
        )

    return _upload


__all__ = [
    "ADMIN_CREDS",
    "INVITE_CODE",
    "LOW_BALANCE_THRESHOLD",
    "MEMBER_CREDS",
    "PARSED_KEYS",
    "Receipt",
    "Restaurant",
    "Transaction",
    "TxType",
    "User",
]
