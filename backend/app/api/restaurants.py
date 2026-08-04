"""식당 라우터 — CONTRACT.md §2.2.

목록은 집계 서브쿼리를 outer join 한 **단일 쿼리**로 처리한다 → 잔액 정렬도 SQL 에서.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import CurrentUser, DbSession
from app.models import Restaurant, Transaction, TxType
from app.schemas.restaurant import (
    RestaurantCreateIn,
    RestaurantDetail,
    RestaurantListOut,
    RestaurantUpdateIn,
)
from app.schemas.transaction import TransactionListOut
from app.services import ledger
from app.services.matching import normalize_business_number

router = APIRouter()

SortKey = Literal["balance_desc", "balance_asc", "name", "recent", "created"]

_NON_DIGITS = re.compile(r"\D+")


def _get_restaurant(db: Session, restaurant_id: int) -> Restaurant:
    restaurant = db.get(Restaurant, restaurant_id)
    if restaurant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="식당을 찾을 수 없습니다."
        )
    return restaurant


def _assert_business_number_free(
    db: Session, business_number: str | None, exclude_id: int | None = None
) -> None:
    """사업자등록번호 중복 방지 — 어느 식당과 겹치는지 이름까지 알려준다."""
    if not business_number:
        return
    stmt = select(Restaurant).where(Restaurant.business_number == business_number)
    if exclude_id is not None:
        stmt = stmt.where(Restaurant.id != exclude_id)
    existing = db.execute(stmt).scalars().first()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"이미 등록된 사업자등록번호입니다. ({existing.name})",
        )


@router.get("", response_model=RestaurantListOut)
@router.get("/", response_model=RestaurantListOut, include_in_schema=False)
def list_restaurants(
    user: CurrentUser,
    db: DbSession,
    query: str | None = Query(default=None, max_length=200),
    sort: SortKey = "balance_desc",
    include_archived: bool = False,
    low_only: bool = False,
) -> dict[str, Any]:
    stats = ledger.restaurant_stats_subquery()
    balance = func.coalesce(stats.c.balance, 0)

    stmt = select(
        Restaurant,
        balance.label("balance"),
        func.coalesce(stats.c.charge_total, 0).label("charge_total"),
        func.coalesce(stats.c.use_total, 0).label("use_total"),
        func.coalesce(stats.c.tx_count, 0).label("tx_count"),
        stats.c.last_used_at.label("last_used_at"),
        stats.c.last_charged_at.label("last_charged_at"),
    ).outerjoin(stats, stats.c.restaurant_id == Restaurant.id)

    if not include_archived:
        stmt = stmt.where(Restaurant.is_archived.is_(False))
    if low_only:
        stmt = stmt.where(balance < settings.low_balance_threshold)

    if query:
        term = query.strip()
        if term:
            like = f"%{term}%"
            conditions = [
                Restaurant.name.ilike(like),
                Restaurant.address.ilike(like),
                Restaurant.business_number.ilike(like),
            ]
            # 숫자만 입력했으면 하이픈을 뺀 사업자번호로도 찾아준다
            digits = _NON_DIGITS.sub("", term)
            if len(digits) >= 3:
                conditions.append(Restaurant.business_number.ilike(f"%{digits}%"))
                conditions.append(Restaurant.phone.ilike(f"%{digits}%"))
            stmt = stmt.where(or_(*conditions))

    if sort == "balance_asc":
        stmt = stmt.order_by(balance.asc(), Restaurant.name.asc())
    elif sort == "name":
        stmt = stmt.order_by(Restaurant.name.asc())
    elif sort == "recent":
        # 최근 활동 순 (거래가 없으면 생성일로 대체 → NULL 정렬 이슈 회피)
        stmt = stmt.order_by(
            func.coalesce(stats.c.last_activity_at, Restaurant.created_at).desc(),
            Restaurant.id.desc(),
        )
    elif sort == "created":
        stmt = stmt.order_by(Restaurant.created_at.desc(), Restaurant.id.desc())
    else:  # balance_desc (기본)
        stmt = stmt.order_by(balance.desc(), Restaurant.name.asc())

    rows = db.execute(stmt).unique().all()
    items = [ledger.build_restaurant_summary(row[0], row) for row in rows]

    totals = ledger.portfolio_totals(db)
    return {
        "items": items,
        "total": len(items),
        "total_balance": totals["total_balance"],
        "low_balance_count": totals["low_balance_count"],
        "low_balance_threshold": settings.low_balance_threshold,
    }


@router.post("", response_model=RestaurantDetail, status_code=status.HTTP_201_CREATED)
@router.post(
    "/",
    response_model=RestaurantDetail,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
def create_restaurant(
    payload: RestaurantCreateIn, user: CurrentUser, db: DbSession
) -> dict[str, Any]:
    business_number = normalize_business_number(payload.business_number)
    _assert_business_number_free(db, business_number)

    restaurant = Restaurant(
        name=payload.name,
        business_number=business_number,
        address=payload.address,
        phone=payload.phone,
        memo=payload.memo,
        created_by=user.id,
    )
    db.add(restaurant)
    try:
        db.flush()
        # 앱 도입 전 이미 선결제해둔 금액 백필 (0 이면 거래를 만들지 않는다)
        if payload.initial_balance > 0:
            ledger.create_transaction(
                db,
                restaurant=restaurant,
                type=TxType.CHARGE,
                amount=payload.initial_balance,
                occurred_at=payload.occurred_at,
                memo=payload.initial_balance_memo or ledger.INITIAL_BALANCE_MEMO,
                actor=user,
                allow_negative=True,
            )
        db.commit()
    except Exception:
        db.rollback()
        raise

    db.refresh(restaurant)
    return ledger.build_restaurant_detail(db, restaurant)


@router.get("/{restaurant_id}", response_model=RestaurantDetail)
def get_restaurant(restaurant_id: int, user: CurrentUser, db: DbSession) -> dict[str, Any]:
    restaurant = _get_restaurant(db, restaurant_id)
    return ledger.build_restaurant_detail(db, restaurant)


@router.patch("/{restaurant_id}", response_model=RestaurantDetail)
def update_restaurant(
    restaurant_id: int, payload: RestaurantUpdateIn, user: CurrentUser, db: DbSession
) -> dict[str, Any]:
    restaurant = _get_restaurant(db, restaurant_id)
    changes = payload.model_dump(exclude_unset=True)  # 보낸 필드만 반영

    if "business_number" in changes:
        raw = changes["business_number"]
        normalized = normalize_business_number(raw)
        if raw and normalized is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="사업자등록번호는 숫자 10자리로 입력해 주세요.",
            )
        _assert_business_number_free(db, normalized, exclude_id=restaurant.id)
        changes["business_number"] = normalized

    for field, value in changes.items():
        setattr(restaurant, field, value)

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(restaurant)
    return ledger.build_restaurant_detail(db, restaurant)


@router.get("/{restaurant_id}/transactions", response_model=TransactionListOut)
def list_restaurant_transactions(
    restaurant_id: int,
    user: CurrentUser,
    db: DbSession,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    include_voided: bool = True,
) -> dict[str, Any]:
    _get_restaurant(db, restaurant_id)
    conditions: list[Any] = [Transaction.restaurant_id == restaurant_id]
    if not include_voided:
        conditions.append(Transaction.voided_at.is_(None))
    return ledger.transaction_list_payload(db, conditions, limit=limit, offset=offset)
