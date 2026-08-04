"""거래 라우터 — CONTRACT.md §2.4."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.deps import CurrentUser, DbSession
from app.core.timeutil import kst_day_bounds
from app.models import Receipt, Restaurant, Transaction, TxType
from app.schemas.transaction import (
    TransactionCreateIn,
    TransactionCreateOut,
    TransactionListOut,
    VoidIn,
)
from app.services import export, ledger

router = APIRouter()

TxTypeFilter = Literal["CHARGE", "USE", "ADJUST"]


def _build_conditions(
    restaurant_id: int | None,
    user_id: int | None,
    tx_type: TxTypeFilter | None,
    date_from: date | None,
    date_to: date | None,
    include_voided: bool,
    query: str | None,
) -> list[Any]:
    """GET / 과 export.csv 가 공유하는 필터 (KST 날짜, 양끝 포함)."""
    conditions: list[Any] = []
    if restaurant_id is not None:
        conditions.append(Transaction.restaurant_id == restaurant_id)
    if user_id is not None:
        conditions.append(Transaction.created_by == user_id)
    if tx_type is not None:
        conditions.append(Transaction.type == TxType(tx_type))
    if date_from is not None:
        conditions.append(Transaction.occurred_at >= kst_day_bounds(date_from)[0])
    if date_to is not None:
        # 종료일 '그 날 끝까지' 포함 → 다음 날 00:00(KST) 미만
        conditions.append(Transaction.occurred_at < kst_day_bounds(date_to)[1])
    if not include_voided:
        conditions.append(Transaction.voided_at.is_(None))
    if query:
        term = query.strip()
        if term:
            like = f"%{term}%"
            conditions.append(or_(Transaction.memo.ilike(like), Restaurant.name.ilike(like)))
    return conditions


def _get_restaurant(db: Session, restaurant_id: int) -> Restaurant:
    restaurant = db.get(Restaurant, restaurant_id)
    if restaurant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="식당을 찾을 수 없습니다."
        )
    return restaurant


@router.get("", response_model=TransactionListOut)
@router.get("/", response_model=TransactionListOut, include_in_schema=False)
def list_transactions(
    user: CurrentUser,
    db: DbSession,
    restaurant_id: int | None = None,
    user_id: int | None = None,
    type: TxTypeFilter | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    include_voided: bool = True,
    query: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    conditions = _build_conditions(
        restaurant_id, user_id, type, date_from, date_to, include_voided, query
    )
    return ledger.transaction_list_payload(db, conditions, limit=limit, offset=offset)


@router.post("", response_model=TransactionCreateOut, status_code=status.HTTP_201_CREATED)
@router.post(
    "/",
    response_model=TransactionCreateOut,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
def create_transaction(
    payload: TransactionCreateIn, user: CurrentUser, db: DbSession
) -> dict[str, Any]:
    restaurant = _get_restaurant(db, payload.restaurant_id)

    if payload.receipt_id is not None and db.get(Receipt, payload.receipt_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="영수증을 찾을 수 없습니다."
        )

    try:
        tx, balance_after, warnings = ledger.create_transaction(
            db,
            restaurant=restaurant,
            type=payload.type,
            amount=payload.amount,
            occurred_at=payload.occurred_at,
            memo=payload.memo,
            receipt_id=payload.receipt_id,
            actor=user,
            allow_negative=payload.allow_negative,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    return {
        "transaction": ledger.serialize_transaction(tx),
        "balance_after": balance_after,
        "warnings": warnings,
    }


@router.post("/{transaction_id}/void", response_model=TransactionCreateOut)
def void_transaction(
    transaction_id: int, payload: VoidIn, user: CurrentUser, db: DbSession
) -> dict[str, Any]:
    tx = db.get(Transaction, transaction_id)
    if tx is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="거래를 찾을 수 없습니다."
        )
    try:
        tx, balance_after, warnings = ledger.void_transaction(db, tx, user, payload.reason)
        db.commit()
    except Exception:
        db.rollback()
        raise

    return {
        "transaction": ledger.serialize_transaction(tx),
        "balance_after": balance_after,
        "warnings": warnings,
    }


@router.get("/export.csv", response_class=Response)
def export_transactions_csv(
    user: CurrentUser,
    db: DbSession,
    restaurant_id: int | None = None,
    user_id: int | None = None,
    type: TxTypeFilter | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    include_voided: bool = True,
    query: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=10_000, ge=1, le=100_000),
    offset: int = Query(default=0, ge=0),
) -> Response:
    conditions = _build_conditions(
        restaurant_id, user_id, type, date_from, date_to, include_voided, query
    )
    rows = ledger.list_transactions(db, conditions, limit=limit, offset=offset)
    body = export.transactions_csv(rows)
    filename = export.csv_filename()
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
