"""영수증 라우터 — CONTRACT.md §2.3.

업로드 → (Pillow 로 EXIF 보정·축소 후 저장) → OCR → 식당 매칭 → 중복 경고 까지
한 번의 응답으로 돌려준다. **OCR 이 실패해도 201** 로 응답하고 프론트가 수동 입력으로 잇는다.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import CurrentUser, DbSession
from app.core.timeutil import kst_today
from app.models import OcrStatus, Receipt
from app.schemas.receipt import ConfirmIn, ConfirmOut, ReceiptUploadOut
from app.services import ledger, ocr
from app.services.matching import match_restaurant, normalize_business_number

log = logging.getLogger("ssel.receipts")

router = APIRouter()

STORED_CONTENT_TYPE = "image/jpeg"  # 저장 시 항상 JPEG 로 정규화한다
STORED_EXT = "jpg"


# ── 저장 경로 ─────────────────────────────────────────────────────


def _new_relative_path() -> str:
    """`YYYY/MM/<uuid4>.jpg` (KST 기준 연/월 디렉터리)."""
    today = kst_today()
    return f"{today.year:04d}/{today.month:02d}/{uuid.uuid4().hex}.{STORED_EXT}"


def _absolute_path(receipt: Receipt) -> Path:
    stored = Path(receipt.image_path)
    if stored.is_absolute():  # 과거 데이터 방어
        return stored
    return settings.upload_dir / stored


# ── 직렬화 ────────────────────────────────────────────────────────


def _parsed_dict(receipt: Receipt) -> dict[str, Any]:
    return {
        "store_name": receipt.parsed_store_name,
        "business_number": receipt.parsed_business_number,
        "address": receipt.parsed_address,
        "phone": receipt.parsed_phone,
        "total_amount": receipt.parsed_total_amount,
        "paid_at": receipt.parsed_paid_at,
    }


def _receipt_dict(receipt: Receipt) -> dict[str, Any]:
    return {
        "id": receipt.id,
        "image_url": f"/api/receipts/{receipt.id}/image",
        "ocr_status": receipt.ocr_status,
        "ocr_error": receipt.ocr_error,
        "ocr_ms": receipt.ocr_ms,
        "created_at": receipt.created_at,
        "consumed_at": receipt.consumed_at,
        "uploaded_by": ledger.user_brief(receipt.uploader),
    }


def _match_dict(db: Session, parsed: dict[str, Any]) -> dict[str, Any]:
    outcome = match_restaurant(db, parsed)
    ids = {c.restaurant.id for c in outcome.candidates}
    if outcome.restaurant is not None:
        ids.add(outcome.restaurant.id)
    stats = ledger.stats_rows_for(db, ids)  # 후보 집계도 쿼리 1회 (N+1 금지)
    return {
        "matched_by": outcome.matched_by,
        "restaurant": (
            ledger.build_restaurant_summary(
                outcome.restaurant, stats.get(outcome.restaurant.id)
            )
            if outcome.restaurant is not None
            else None
        ),
        "candidates": [
            {
                "restaurant": ledger.build_restaurant_summary(
                    c.restaurant, stats.get(c.restaurant.id)
                ),
                "score": c.score,
                "reason": c.reason,
            }
            for c in outcome.candidates
        ],
    }


def _upload_payload(db: Session, receipt: Receipt) -> dict[str, Any]:
    parsed = _parsed_dict(receipt)
    return {
        "receipt": _receipt_dict(receipt),
        "parsed": parsed,
        "match": _match_dict(db, parsed),
        "duplicate": ledger.find_duplicate_receipt(db, receipt),
    }


# ── OCR 실행 ──────────────────────────────────────────────────────


def _run_ocr(receipt: Receipt) -> None:
    """OCR 을 돌려 결과를 receipt 에 반영한다. 예외는 절대 올라오지 않는다 (§3)."""
    provider = ocr.get_ocr_provider()
    result = provider.extract(_absolute_path(receipt))

    receipt.ocr_error = result.error
    receipt.ocr_raw = result.raw
    receipt.ocr_ms = result.elapsed_ms
    receipt.ocr_status = OcrStatus.failed if result.error else OcrStatus.done
    if result.error:
        log.warning("영수증 %s OCR 실패: %s", receipt.id, result.error)

    # 프로바이더가 준 값의 타입을 믿지 않는다 — paid_at 은 문자열로 올 수도 있고
    # (ParsedReceipt.paid_at 은 계약상 문자열), 금액도 "42,000원" 일 수 있다.
    # 이미 datetime 이면 그대로 둔다 (다시 변환하면 KST 로 재해석돼 9시간 밀린다).
    parsed = result.parsed or {}
    paid_at = parsed.get("paid_at")
    if paid_at is not None and not isinstance(paid_at, datetime):
        paid_at = ocr.parse_datetime(paid_at)

    receipt.parsed_store_name = parsed.get("store_name")
    receipt.parsed_business_number = normalize_business_number(parsed.get("business_number"))
    receipt.parsed_address = parsed.get("address")
    receipt.parsed_phone = parsed.get("phone")
    receipt.parsed_total_amount = ocr.parse_amount(parsed.get("total_amount"))
    receipt.parsed_paid_at = paid_at


# ── 엔드포인트 ────────────────────────────────────────────────────


@router.post("", response_model=ReceiptUploadOut, status_code=status.HTTP_201_CREATED)
@router.post(
    "/",
    response_model=ReceiptUploadOut,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
async def upload_receipt(
    user: CurrentUser,
    db: DbSession,
    file: UploadFile = File(...),
) -> dict[str, Any]:
    content_type = (file.content_type or "").lower()
    if content_type and not content_type.startswith("image/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="이미지 파일만 업로드할 수 있습니다.",
        )

    raw = await file.read()
    # 헤더(content-length)를 믿지 않고 실제로 읽은 바이트로 판정한다
    if len(raw) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"파일이 너무 큽니다. (최대 {settings.max_upload_mb}MB)",
        )
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="빈 파일입니다."
        )

    try:
        # EXIF 회전 보정(폰 사진 필수) + 긴 변 축소 후 JPEG 로 저장
        image_bytes = ocr.prepare_image_bytes(raw)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="이미지를 읽을 수 없습니다."
        ) from None

    relative = _new_relative_path()
    target = settings.upload_dir / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(image_bytes)

    receipt = Receipt(
        image_path=relative,
        original_filename=(file.filename or None),
        content_type=STORED_CONTENT_TYPE,
        ocr_status=OcrStatus.pending,
        uploaded_by=user.id,
    )
    receipt.uploader = user
    db.add(receipt)
    try:
        db.commit()
    except Exception:
        db.rollback()
        target.unlink(missing_ok=True)  # 고아 파일 남기지 않기
        raise
    db.refresh(receipt)

    # OCR 은 외부 HTTP 호출이므로 DB 쓰기 락을 잡지 않은 상태에서 실행한다.
    # 실패해도 정상 흐름 (ocr_status=failed) — 프론트가 수동 입력으로 잇는다.
    _run_ocr(receipt)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(receipt)
    return _upload_payload(db, receipt)


def _get_receipt(db: Session, receipt_id: int) -> Receipt:
    receipt = db.get(Receipt, receipt_id)
    if receipt is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="영수증을 찾을 수 없습니다."
        )
    return receipt


@router.get("/{receipt_id}", response_model=ReceiptUploadOut)
def get_receipt(receipt_id: int, user: CurrentUser, db: DbSession) -> dict[str, Any]:
    """재조회 — OCR 을 다시 돌리지 않는다."""
    return _upload_payload(db, _get_receipt(db, receipt_id))


@router.get("/{receipt_id}/image", response_class=FileResponse)
def get_receipt_image(receipt_id: int, user: CurrentUser, db: DbSession) -> FileResponse:
    """인증된 사용자에게만 원본 이미지를 준다."""
    receipt = _get_receipt(db, receipt_id)
    path = _absolute_path(receipt)
    if not path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="이미지를 찾을 수 없습니다."
        )
    return FileResponse(
        path,
        media_type=receipt.content_type or STORED_CONTENT_TYPE,
        filename=receipt.original_filename or path.name,
        content_disposition_type="inline",
    )


@router.post("/{receipt_id}/reocr", response_model=ReceiptUploadOut)
def reocr_receipt(receipt_id: int, user: CurrentUser, db: DbSession) -> dict[str, Any]:
    receipt = _get_receipt(db, receipt_id)
    # 이미 확정된 영수증의 parsed 값을 덮어쓰면 감사 기록이 어긋난다
    if receipt.consumed_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="이미 처리된 영수증입니다."
        )
    if not _absolute_path(receipt).is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="이미지를 찾을 수 없습니다."
        )
    try:
        _run_ocr(receipt)
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(receipt)
    return _upload_payload(db, receipt)


@router.post("/{receipt_id}/confirm", response_model=ConfirmOut)
def confirm_receipt(
    receipt_id: int, payload: ConfirmIn, user: CurrentUser, db: DbSession
) -> dict[str, Any]:
    receipt = _get_receipt(db, receipt_id)
    return ledger.confirm_receipt(db, receipt, payload, user)
