"""통계 스키마 — CONTRACT.md §2.5."""

from __future__ import annotations

from pydantic import Field

from app.schemas.common import ApiModel
from app.schemas.restaurant import RestaurantSummary
from app.schemas.transaction import TransactionOut


class SummaryOut(ApiModel):
    total_balance: int
    restaurant_count: int
    low_balance_count: int
    low_balance_threshold: int
    month: str  # "YYYY-MM" (KST)
    month_charge: int
    month_use: int
    all_time_charge: int
    all_time_use: int
    recent_transactions: list[TransactionOut] = Field(default_factory=list)  # 10건
    low_balance_restaurants: list[RestaurantSummary] = Field(default_factory=list)  # 5건


class MonthlyPoint(ApiModel):
    month: str  # "YYYY-MM" (KST)
    charge: int
    use: int
    net: int  # charge - use


class MonthlyOut(ApiModel):
    items: list[MonthlyPoint] = Field(default_factory=list)  # 오래된 달 → 최근 달 순


class RestaurantStatRow(ApiModel):
    restaurant_id: int
    name: str
    charge: int  # 기간 내 충전 합
    use: int  # 기간 내 사용 합
    balance: int  # 현재 잔액 (기간 무관, 전체 누적)


class UserStatRow(ApiModel):
    user_id: int | None = None
    name: str
    charge: int
    use: int
    tx_count: int
