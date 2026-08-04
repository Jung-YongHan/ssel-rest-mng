"""식당 스키마 — CONTRACT.md §2.2."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import ApiModel, UtcOut
from app.schemas.transaction import KstDateTime, TransactionOut


def _blank_to_none(v: str | None) -> str | None:
    """빈 문자열은 NULL 로 저장한다 (프론트 입력창이 '' 를 보내는 경우)."""
    if v is None:
        return None
    v = v.strip()
    return v or None


class RestaurantSummary(ApiModel):
    id: int
    name: str
    business_number: str | None = None  # 숫자 10자리 (표시할 때만 하이픈)
    address: str | None = None
    phone: str | None = None
    memo: str | None = None
    is_archived: bool
    balance: int  # 현재 잔액 (음수 가능)
    charge_total: int  # 누적 충전 (void 제외)
    use_total: int  # 누적 사용 (void 제외)
    tx_count: int  # 유효 거래 수
    last_used_at: UtcOut | None = None
    last_charged_at: UtcOut | None = None
    is_low_balance: bool
    created_at: UtcOut
    updated_at: UtcOut


class RestaurantDetail(RestaurantSummary):
    recent_transactions: list[TransactionOut] = Field(default_factory=list)


class RestaurantListOut(ApiModel):
    items: list[RestaurantSummary]
    total: int
    total_balance: int  # 전체 합계 (archived 제외)
    low_balance_count: int
    low_balance_threshold: int


class RestaurantCreateIn(BaseModel):
    """앱 도입 전 이미 선결제해둔 식당 백필 지원 (`initial_balance`)."""

    name: str = Field(min_length=1, max_length=200)
    business_number: str | None = Field(default=None, max_length=40)
    address: str | None = Field(default=None, max_length=300)
    phone: str | None = Field(default=None, max_length=40)
    memo: str | None = Field(default=None, max_length=2000)
    initial_balance: int = Field(default=0, ge=0)
    initial_balance_memo: str | None = Field(default=None, max_length=2000)
    occurred_at: KstDateTime | None = None

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("식당 이름을 입력해 주세요.")
        return v

    @field_validator("business_number", "address", "phone", "memo", "initial_balance_memo")
    @classmethod
    def _clean(cls, v: str | None) -> str | None:
        return _blank_to_none(v)


class RestaurantUpdateIn(BaseModel):
    """전부 optional. **보낸 필드만** 반영한다 (`model_fields_set` 사용)."""

    name: str | None = Field(default=None, max_length=200)
    business_number: str | None = Field(default=None, max_length=40)
    address: str | None = Field(default=None, max_length=300)
    phone: str | None = Field(default=None, max_length=40)
    memo: str | None = Field(default=None, max_length=2000)
    is_archived: bool | None = None

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            raise ValueError("식당 이름을 입력해 주세요.")
        return v

    @field_validator("business_number", "address", "phone", "memo")
    @classmethod
    def _clean(cls, v: str | None) -> str | None:
        return _blank_to_none(v)
