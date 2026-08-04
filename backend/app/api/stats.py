"""통계 라우터 — CONTRACT.md §2.5.

월 단위 집계는 DB 방언에 의존하는 날짜 함수 대신 **KST 로 파이썬에서 버킷팅**한다
(SQLite/PG 모두 동일 결과 보장. 연구실 규모에서는 비용도 무시할 만하다).
"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import CurrentUser, DbSession
from app.core.timeutil import (
    kst_day_bounds,
    kst_month_bounds,
    kst_month_key,
    kst_today,
)
from app.models import Restaurant, Transaction, TxType, User
from app.schemas.stats import MonthlyOut, RestaurantStatRow, SummaryOut, UserStatRow
from app.services import ledger

router = APIRouter()

_CHARGE = case((Transaction.type == TxType.CHARGE, Transaction.amount), else_=0)
_USE = case((Transaction.type == TxType.USE, Transaction.amount), else_=0)


def _range_conditions(date_from: date | None, date_to: date | None) -> list[Any]:
    """KST 날짜 양끝 포함 → naive UTC 범위 조건."""
    conditions: list[Any] = [Transaction.voided_at.is_(None)]
    if date_from is not None:
        conditions.append(Transaction.occurred_at >= kst_day_bounds(date_from)[0])
    if date_to is not None:
        conditions.append(Transaction.occurred_at < kst_day_bounds(date_to)[1])
    return conditions


def _sum_charge_use(db: Session, *conditions: Any) -> tuple[int, int]:
    row = db.execute(
        select(
            func.coalesce(func.sum(_CHARGE), 0),
            func.coalesce(func.sum(_USE), 0),
        ).where(*conditions)
    ).one()
    return int(row[0] or 0), int(row[1] or 0)


@router.get("/summary", response_model=SummaryOut)
def summary(user: CurrentUser, db: DbSession) -> dict[str, Any]:
    totals = ledger.portfolio_totals(db)

    today = kst_today()
    month_start, month_end = kst_month_bounds(today.year, today.month)
    month_charge, month_use = _sum_charge_use(
        db,
        Transaction.voided_at.is_(None),
        Transaction.occurred_at >= month_start,
        Transaction.occurred_at < month_end,
    )
    all_charge, all_use = _sum_charge_use(db, Transaction.voided_at.is_(None))

    recent = ledger.list_transactions(db, [Transaction.voided_at.is_(None)], limit=10, offset=0)

    # 잔액 부족 식당 5곳 — 집계 서브쿼리 join 1회로 정렬까지 SQL 에서
    stats = ledger.restaurant_stats_subquery()
    balance = func.coalesce(stats.c.balance, 0)
    low_rows = (
        db.execute(
            select(
                Restaurant,
                balance.label("balance"),
                func.coalesce(stats.c.charge_total, 0).label("charge_total"),
                func.coalesce(stats.c.use_total, 0).label("use_total"),
                func.coalesce(stats.c.tx_count, 0).label("tx_count"),
                stats.c.last_used_at.label("last_used_at"),
                stats.c.last_charged_at.label("last_charged_at"),
            )
            .outerjoin(stats, stats.c.restaurant_id == Restaurant.id)
            .where(
                Restaurant.is_archived.is_(False),
                balance < settings.low_balance_threshold,
            )
            .order_by(balance.asc(), Restaurant.name.asc())
            .limit(5)
        )
        .unique()
        .all()
    )

    return {
        "total_balance": totals["total_balance"],
        "restaurant_count": totals["restaurant_count"],
        "low_balance_count": totals["low_balance_count"],
        "low_balance_threshold": settings.low_balance_threshold,
        "month": f"{today.year:04d}-{today.month:02d}",
        "month_charge": month_charge,
        "month_use": month_use,
        "all_time_charge": all_charge,
        "all_time_use": all_use,
        "recent_transactions": [ledger.serialize_transaction(t) for t in recent],
        "low_balance_restaurants": [
            ledger.build_restaurant_summary(row[0], row) for row in low_rows
        ],
    }


@router.get("/monthly", response_model=MonthlyOut)
def monthly(
    user: CurrentUser, db: DbSession, months: int = Query(default=12, ge=1, le=60)
) -> dict[str, Any]:
    today = kst_today()
    keys: list[tuple[int, int]] = []
    for back in range(months - 1, -1, -1):
        year, month = today.year, today.month - back
        while month <= 0:
            month += 12
            year -= 1
        keys.append((year, month))

    start = kst_month_bounds(*keys[0])[0]
    end = kst_month_bounds(*keys[-1])[1]

    rows = db.execute(
        select(Transaction.occurred_at, Transaction.type, Transaction.amount).where(
            Transaction.voided_at.is_(None),
            Transaction.occurred_at >= start,
            Transaction.occurred_at < end,
        )
    ).all()

    buckets: dict[str, dict[str, int]] = {
        f"{y:04d}-{m:02d}": {"charge": 0, "use": 0} for y, m in keys
    }
    for occurred_at, tx_type, amount in rows:
        bucket = buckets.get(kst_month_key(occurred_at))
        if bucket is None:  # 경계 밖 (이론상 없음)
            continue
        if tx_type == TxType.CHARGE:
            bucket["charge"] += int(amount)
        elif tx_type == TxType.USE:
            bucket["use"] += int(amount)

    return {
        "items": [
            {
                "month": key,
                "charge": value["charge"],
                "use": value["use"],
                "net": value["charge"] - value["use"],
            }
            for key, value in buckets.items()
        ]
    }


@router.get("/by-restaurant", response_model=dict[str, list[RestaurantStatRow]])
def by_restaurant(
    user: CurrentUser,
    db: DbSession,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """기간 내 충전/사용 + 현재 잔액 (잔액은 기간과 무관한 누적값)."""
    period = (
        select(
            Transaction.restaurant_id.label("restaurant_id"),
            func.coalesce(func.sum(_CHARGE), 0).label("charge"),
            func.coalesce(func.sum(_USE), 0).label("use"),
        )
        .where(*_range_conditions(date_from, date_to))
        .group_by(Transaction.restaurant_id)
        .subquery("period_stats")
    )
    stats = ledger.restaurant_stats_subquery()

    rows = db.execute(
        select(
            Restaurant.id,
            Restaurant.name,
            func.coalesce(period.c.charge, 0),
            func.coalesce(period.c.use, 0),
            func.coalesce(stats.c.balance, 0),
        )
        .outerjoin(period, period.c.restaurant_id == Restaurant.id)
        .outerjoin(stats, stats.c.restaurant_id == Restaurant.id)
        .where(Restaurant.is_archived.is_(False))
        .order_by(
            func.coalesce(period.c.use, 0).desc(),
            func.coalesce(period.c.charge, 0).desc(),
            Restaurant.name.asc(),
        )
    ).all()

    return {
        "items": [
            {
                "restaurant_id": int(row[0]),
                "name": row[1],
                "charge": int(row[2] or 0),
                "use": int(row[3] or 0),
                "balance": int(row[4] or 0),
            }
            for row in rows
        ]
    }


@router.get("/by-user", response_model=dict[str, list[UserStatRow]])
def by_user(
    user: CurrentUser,
    db: DbSession,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict[str, list[dict[str, Any]]]:
    rows = db.execute(
        select(
            Transaction.created_by,
            func.max(User.name),
            func.coalesce(func.sum(_CHARGE), 0),
            func.coalesce(func.sum(_USE), 0),
            func.count(Transaction.id),
        )
        .select_from(Transaction)
        .outerjoin(User, User.id == Transaction.created_by)
        .where(*_range_conditions(date_from, date_to))
        .group_by(Transaction.created_by)
        .order_by(func.count(Transaction.id).desc())
    ).all()

    return {
        "items": [
            {
                "user_id": int(row[0]) if row[0] is not None else None,
                "name": row[1] or "(알 수 없음)",
                "charge": int(row[2] or 0),
                "use": int(row[3] or 0),
                "tx_count": int(row[4] or 0),
            }
            for row in rows
        ]
    }
