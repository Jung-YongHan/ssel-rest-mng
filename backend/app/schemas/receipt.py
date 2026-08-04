"""영수증 스키마 — CONTRACT.md §2.3."""

from __future__ import annotations

import enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, PlainSerializer, field_validator

from app.core.timeutil import as_utc_aware
from app.schemas.common import ApiModel, UserBrief, UtcOut
from app.schemas.restaurant import RestaurantDetail, RestaurantSummary
from app.schemas.transaction import KstDateTime, TransactionOut

# ParsedReceipt 는 응답이면서 confirm 요청의 입력이기도 하다 → 입출력 규약을 한 타입에 담는다.
#   입력: 문자열 → datetime → (naive 면 KST 벽시계) → naive UTC
#   출력: naive UTC → '...+00:00'
KstInUtcOut = Annotated[
    KstDateTime,
    PlainSerializer(lambda d: as_utc_aware(d).isoformat(), return_type=str, when_used="json"),
]


def _enum_value(v: Any) -> Any:
    return v.value if isinstance(v, enum.Enum) else v


def _blank_to_none(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip()
    return v or None


class ParsedReceipt(BaseModel):
    """**요청용** — 사용자가 화면에서 고친 값 (`ConfirmIn.parsed`).

    `paid_at` 은 naive 입력을 KST 벽시계로 해석한다.
    """

    store_name: str | None = Field(default=None, max_length=200)
    business_number: str | None = Field(default=None, max_length=40)
    address: str | None = Field(default=None, max_length=300)
    phone: str | None = Field(default=None, max_length=40)
    total_amount: int | None = None  # 부가세 포함 합계금액
    paid_at: KstInUtcOut | None = None

    @field_validator("store_name", "business_number", "address", "phone")
    @classmethod
    def _clean(cls, v: str | None) -> str | None:
        return _blank_to_none(v)


class ParsedReceiptOut(BaseModel):
    """**응답용** — 와이어 형식은 ParsedReceipt 와 같다 (프론트는 같은 타입으로 취급).

    ⚠️ 응답에는 KST 입력 변환기를 붙이면 안 된다. DB 값은 이미 naive UTC 이므로
    입력용 타입(`KstInUtcOut`)으로 응답을 만들면 **한 번 더 KST 로 재해석되어
    9시간 어긋난다.** 그래서 출력 전용 `UtcOut` 을 쓴다.
    """

    store_name: str | None = None
    business_number: str | None = None
    address: str | None = None
    phone: str | None = None
    total_amount: int | None = None
    paid_at: UtcOut | None = None


class ReceiptOut(ApiModel):
    id: int
    image_url: str  # "/api/receipts/{id}/image"
    ocr_status: Literal["pending", "done", "failed"]
    ocr_error: str | None = None
    ocr_ms: int | None = None
    created_at: UtcOut
    consumed_at: UtcOut | None = None
    uploaded_by: UserBrief | None = None

    @field_validator("ocr_status", mode="before")
    @classmethod
    def _status_value(cls, v: Any) -> Any:
        return _enum_value(v)


class MatchCandidate(ApiModel):
    restaurant: RestaurantSummary
    score: int
    reason: Literal["business_number", "name"]


class MatchResult(ApiModel):
    matched_by: Literal["business_number", "name"] | None = None
    restaurant: RestaurantSummary | None = None  # 확정 매칭 (name 은 score>=88 자동확정)
    candidates: list[MatchCandidate] = Field(default_factory=list)


class DuplicateInfo(ApiModel):
    receipt_id: int
    transaction_id: int | None = None
    restaurant_name: str | None = None
    message: str


class ReceiptUploadOut(ApiModel):
    receipt: ReceiptOut
    parsed: ParsedReceiptOut  # 응답 전용 타입 — 이유는 ParsedReceiptOut docstring 참고
    match: MatchResult
    duplicate: DuplicateInfo | None = None


class ConfirmRestaurantIn(BaseModel):
    """`action="register_and_charge"` 에서 새로 만들 식당 정보."""

    name: str = Field(min_length=1, max_length=200)
    business_number: str | None = Field(default=None, max_length=40)
    address: str | None = Field(default=None, max_length=300)
    phone: str | None = Field(default=None, max_length=40)
    memo: str | None = Field(default=None, max_length=2000)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("식당 이름을 입력해 주세요.")
        return v

    @field_validator("business_number", "address", "phone", "memo")
    @classmethod
    def _clean(cls, v: str | None) -> str | None:
        return _blank_to_none(v)


class ConfirmIn(BaseModel):
    action: Literal["register_and_charge", "charge", "use"]
    restaurant_id: int | None = None  # charge/use 필수
    restaurant: ConfirmRestaurantIn | None = None  # register_and_charge 필수
    charge_amount: int | None = None  # register_and_charge/charge 필수, >0
    use_amount: int | None = None  # 선택, 0/null 이면 USE 거래를 만들지 않는다
    occurred_at: KstInUtcOut | None = None  # 기본 parsed_paid_at ?? now
    memo: str | None = Field(default=None, max_length=2000)
    allow_negative: bool = False
    parsed: ParsedReceipt | None = None  # 사용자가 고친 값 → receipt 에 반영 저장


class ConfirmOut(ApiModel):
    restaurant: RestaurantDetail
    transactions: list[TransactionOut] = Field(default_factory=list)  # CHARGE, USE 순
    balance_before: int
    balance_after: int
    warnings: list[str] = Field(default_factory=list)


__all__ = [
    "ConfirmIn",
    "ConfirmOut",
    "ConfirmRestaurantIn",
    "DuplicateInfo",
    "MatchCandidate",
    "MatchResult",
    "ParsedReceipt",
    "ParsedReceiptOut",
    "ReceiptOut",
    "ReceiptUploadOut",
]
