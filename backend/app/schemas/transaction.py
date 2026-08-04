"""거래 스키마 — CONTRACT.md §2.4.

이 모듈은 스키마 import 사슬의 시작점(common → transaction → restaurant → receipt)이라
공용 입력 datetime 타입 `KstDateTime` 도 여기서 정의한다.
"""

from __future__ import annotations

import enum
from typing import Annotated, Any, Literal

from dateutil import parser as date_parser
from pydantic import BaseModel, BeforeValidator, Field, field_validator

from app.schemas.common import ApiModel, KstIn, UserBrief, UtcOut

TxTypeStr = Literal["CHARGE", "USE", "ADJUST"]


def _enum_value(v: Any) -> Any:
    return v.value if isinstance(v, enum.Enum) else v


def _coerce_datetime(v: Any) -> Any:
    """문자열 입력을 먼저 datetime 으로 만든다.

    `common.KstIn` 은 datetime 객체만 KST→UTC 변환하므로, JSON 으로 들어오는
    `"2026-08-04T12:30"` 같은 **문자열**은 그 전에 datetime 으로 파싱해 줘야
    "naive 입력 = KST 벽시계" 규약(§0)이 실제로 적용된다.
    """
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        try:
            return date_parser.parse(s)
        except (ValueError, OverflowError):
            raise ValueError("날짜/시간 형식이 올바르지 않습니다.") from None
    return v


# 요청용 datetime: 문자열 파싱 → (naive 면 KST 로 해석) → naive UTC
KstDateTime = Annotated[KstIn, BeforeValidator(_coerce_datetime)]


class TransactionOut(ApiModel):
    id: int
    restaurant_id: int
    restaurant_name: str
    type: TxTypeStr
    amount: int  # 항상 원본 금액 (CHARGE/USE 는 양수, ADJUST 는 부호 포함)
    signed_amount: int  # 잔액에 반영되는 값. void 면 0
    occurred_at: UtcOut
    memo: str | None = None
    receipt_id: int | None = None
    has_receipt: bool
    created_by: UserBrief | None = None
    created_at: UtcOut
    is_voided: bool
    voided_at: UtcOut | None = None
    voided_by: UserBrief | None = None
    void_reason: str | None = None

    @field_validator("type", mode="before")
    @classmethod
    def _type_value(cls, v: Any) -> Any:
        return _enum_value(v)


class TransactionCreateIn(BaseModel):
    restaurant_id: int
    type: TxTypeStr
    amount: int  # 부호 검증은 ledger 에서 (한국어 422)
    occurred_at: KstDateTime | None = None
    memo: str | None = Field(default=None, max_length=2000)
    receipt_id: int | None = None
    allow_negative: bool = False


class TransactionCreateOut(ApiModel):
    transaction: TransactionOut
    balance_after: int
    warnings: list[str] = Field(default_factory=list)


class TransactionListOut(ApiModel):
    items: list[TransactionOut]
    total: int
    limit: int
    offset: int
    # 아래 합계는 void 제외 + 페이지가 아니라 필터 전체 기준
    sum_charge: int
    sum_use: int
    sum_adjust: int


class VoidIn(BaseModel):
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("reason")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("취소 사유를 입력해 주세요.")
        return v


__all__ = [
    "KstDateTime",
    "TransactionCreateIn",
    "TransactionCreateOut",
    "TransactionListOut",
    "TransactionOut",
    "TxTypeStr",
    "VoidIn",
]
