"""원장(ledger) 서비스 — 잔액 계산 · 거래 생성/취소 · 영수증 확정.

설계 규칙
- **잔액 컬럼은 없다.** 항상 transactions 합으로 계산한다 (voided 제외).
- 기록은 삭제하지 않는다. void 로 무효화하고 사유를 남긴다.
- **커밋은 라우터가 한다.** 이 모듈은 `flush()` 까지만 해서 confirm 처럼
  여러 거래를 하나의 DB 트랜잭션으로 묶을 수 있게 한다.
  (`flush()` 는 반드시 필요하다 — 다음 잔액 계산 SELECT 가 직전 INSERT 를 봐야 한다.)
- 목록/정렬/집계는 서브쿼리 1회로 처리한다 (N+1 금지).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException, status
from sqlalchemy import Row, Select, case, func, select
from sqlalchemy.orm import Session, contains_eager
from sqlalchemy.sql.selectable import Subquery

from app.core.config import settings
from app.core.timeutil import utc_now
from app.models import (
    SIGNED_AMOUNT_SQL,
    Receipt,
    Restaurant,
    Transaction,
    TxType,
    User,
)
from app.services.matching import normalize_business_number

if TYPE_CHECKING:  # 런타임 import 순환 방지 (스키마는 타입 힌트로만 쓴다)
    from app.schemas.receipt import ConfirmIn

NEGATIVE_BALANCE_WARNING = "잔액이 부족해 음수가 되었습니다."
INITIAL_BALANCE_MEMO = "초기 잔액 등록"


class InsufficientBalance(HTTPException):
    """USE 가 잔액을 음수로 만들 때. `allow_negative=true` 재요청으로 통과시킨다.

    HTTPException 을 상속해 FastAPI 가 그대로 409 로 응답한다 (§2.3/§2.4 규약).
    """

    def __init__(self, balance: int) -> None:
        self.balance = balance
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"잔액이 부족합니다. (현재 {balance:,}원) 계속하려면 확인해 주세요.",
        )


# 유형별 합계용 SQL 조각 (ADJUST 는 충전/사용 합계에 넣지 않고 balance 에만 반영)
_CHARGE_AMOUNT = case((Transaction.type == TxType.CHARGE, Transaction.amount), else_=0)
_USE_AMOUNT = case((Transaction.type == TxType.USE, Transaction.amount), else_=0)
_ADJUST_AMOUNT = case((Transaction.type == TxType.ADJUST, Transaction.amount), else_=0)


# ── 잔액 ──────────────────────────────────────────────────────────


def balance_for(db: Session, restaurant_id: int) -> int:
    """식당 한 곳의 현재 잔액."""
    value = db.execute(
        select(func.coalesce(func.sum(SIGNED_AMOUNT_SQL), 0)).where(
            Transaction.restaurant_id == restaurant_id,
            Transaction.voided_at.is_(None),
        )
    ).scalar()
    return int(value or 0)


def balances_for_all(db: Session, restaurant_ids: Iterable[int]) -> dict[int, int]:
    """여러 식당의 잔액을 한 번의 쿼리로 (N+1 금지). 거래가 없으면 0."""
    ids = [int(i) for i in restaurant_ids]
    if not ids:
        return {}
    rows = db.execute(
        select(
            Transaction.restaurant_id,
            func.coalesce(func.sum(SIGNED_AMOUNT_SQL), 0),
        )
        .where(
            Transaction.restaurant_id.in_(ids),
            Transaction.voided_at.is_(None),
        )
        .group_by(Transaction.restaurant_id)
    ).all()
    result = dict.fromkeys(ids, 0)
    for restaurant_id, total in rows:
        result[int(restaurant_id)] = int(total or 0)
    return result


def restaurant_stats_subquery() -> Subquery:
    """식당별 집계 서브쿼리 (void 제외).

    컬럼: restaurant_id, balance, charge_total, use_total, tx_count,
          last_used_at, last_charged_at, last_activity_at
    목록 쿼리에서 outer join 해 쓰면 정렬/필터를 전부 SQL 에서 처리할 수 있다.
    """
    return (
        select(
            Transaction.restaurant_id.label("restaurant_id"),
            func.coalesce(func.sum(SIGNED_AMOUNT_SQL), 0).label("balance"),
            func.coalesce(func.sum(_CHARGE_AMOUNT), 0).label("charge_total"),
            func.coalesce(func.sum(_USE_AMOUNT), 0).label("use_total"),
            func.count(Transaction.id).label("tx_count"),
            func.max(
                case((Transaction.type == TxType.USE, Transaction.occurred_at))
            ).label("last_used_at"),
            func.max(
                case((Transaction.type == TxType.CHARGE, Transaction.occurred_at))
            ).label("last_charged_at"),
            func.max(Transaction.occurred_at).label("last_activity_at"),
        )
        .where(Transaction.voided_at.is_(None))
        .group_by(Transaction.restaurant_id)
        .subquery("restaurant_stats")
    )


def stats_row_for(db: Session, restaurant_id: int) -> Row[Any] | None:
    """식당 한 곳의 집계 행 (거래가 없으면 None)."""
    stats = restaurant_stats_subquery()
    return db.execute(select(stats).where(stats.c.restaurant_id == restaurant_id)).first()


def stats_rows_for(db: Session, restaurant_ids: Iterable[int]) -> dict[int, Row[Any]]:
    """여러 식당의 집계 행을 한 번의 쿼리로 (매칭 후보 직렬화용)."""
    ids = [int(i) for i in restaurant_ids]
    if not ids:
        return {}
    stats = restaurant_stats_subquery()
    rows = db.execute(select(stats).where(stats.c.restaurant_id.in_(ids))).all()
    return {int(row.restaurant_id): row for row in rows}


def build_summaries(db: Session, restaurants: Sequence[Restaurant]) -> list[dict[str, Any]]:
    """식당 목록 → RestaurantSummary dict 목록 (집계 쿼리 1회, N+1 금지)."""
    if not restaurants:
        return []
    rows = stats_rows_for(db, [r.id for r in restaurants])
    return [build_restaurant_summary(r, rows.get(r.id)) for r in restaurants]


def portfolio_totals(db: Session) -> dict[str, int]:
    """archived 제외 전체 합계 — 홈/통계 카드용. 쿼리 1회."""
    stats = restaurant_stats_subquery()
    balance = func.coalesce(stats.c.balance, 0)
    row = db.execute(
        select(
            func.count(Restaurant.id),
            func.coalesce(func.sum(balance), 0),
            func.coalesce(
                func.sum(case((balance < settings.low_balance_threshold, 1), else_=0)), 0
            ),
        )
        .select_from(Restaurant)
        .outerjoin(stats, stats.c.restaurant_id == Restaurant.id)
        .where(Restaurant.is_archived.is_(False))
    ).one()
    return {
        "restaurant_count": int(row[0] or 0),
        "total_balance": int(row[1] or 0),
        "low_balance_count": int(row[2] or 0),
    }


# ── 직렬화 헬퍼 (모든 엔드포인트가 동일한 모양을 내보내도록) ─────────


def _stat(row: Any, key: str) -> Any:
    if row is None:
        return None
    if isinstance(row, dict):
        return row.get(key)
    return getattr(row, key, None)


def _int(value: Any) -> int:
    return int(value or 0)


def user_brief(user: User | None) -> dict[str, Any] | None:
    if user is None:
        return None
    return {"id": user.id, "name": user.name, "email": user.email}


def build_restaurant_summary(restaurant: Restaurant, stats_row: Any = None) -> dict[str, Any]:
    """RestaurantSummary 모양의 dict. `stats_row` 가 없으면 전부 0 으로 본다."""
    balance = _int(_stat(stats_row, "balance"))
    return {
        "id": restaurant.id,
        "name": restaurant.name,
        "business_number": restaurant.business_number,
        "address": restaurant.address,
        "phone": restaurant.phone,
        "memo": restaurant.memo,
        "is_archived": bool(restaurant.is_archived),
        "balance": balance,
        "charge_total": _int(_stat(stats_row, "charge_total")),
        "use_total": _int(_stat(stats_row, "use_total")),
        "tx_count": _int(_stat(stats_row, "tx_count")),
        "last_used_at": _stat(stats_row, "last_used_at"),
        "last_charged_at": _stat(stats_row, "last_charged_at"),
        # 음수도 당연히 '잔액 부족'
        "is_low_balance": balance < settings.low_balance_threshold,
        "created_at": restaurant.created_at,
        "updated_at": restaurant.updated_at,
    }


def serialize_transaction(tx: Transaction) -> dict[str, Any]:
    """TransactionOut 모양의 dict."""
    restaurant = tx.restaurant
    return {
        "id": tx.id,
        "restaurant_id": tx.restaurant_id,
        "restaurant_name": restaurant.name if restaurant is not None else "",
        "type": tx.type.value if hasattr(tx.type, "value") else str(tx.type),
        "amount": int(tx.amount),
        "signed_amount": int(tx.signed_amount),
        "occurred_at": tx.occurred_at,
        "memo": tx.memo,
        "receipt_id": tx.receipt_id,
        "has_receipt": tx.receipt_id is not None,
        "created_by": user_brief(tx.creator),
        "created_at": tx.created_at,
        "is_voided": tx.is_voided,
        "voided_at": tx.voided_at,
        "voided_by": user_brief(tx.voider),
        "void_reason": tx.void_reason,
    }


# ── 거래 조회 ─────────────────────────────────────────────────────


def transaction_query(*conditions: Any) -> Select[tuple[Transaction]]:
    """식당을 한 번만 join 해서 `restaurant_name` 을 채운다 (N+1 금지)."""
    return (
        select(Transaction)
        .join(Transaction.restaurant)
        .options(contains_eager(Transaction.restaurant))
        .where(*conditions)
        .order_by(Transaction.occurred_at.desc(), Transaction.id.desc())
    )


def count_transactions(db: Session, *conditions: Any) -> int:
    return int(
        db.execute(
            select(func.count(Transaction.id))
            .select_from(Transaction)
            .join(Transaction.restaurant)
            .where(*conditions)
        ).scalar()
        or 0
    )


def transaction_sums(db: Session, *conditions: Any) -> dict[str, int]:
    """필터 전체 기준 합계 (void 는 항상 제외)."""
    row = db.execute(
        select(
            func.coalesce(func.sum(_CHARGE_AMOUNT), 0),
            func.coalesce(func.sum(_USE_AMOUNT), 0),
            func.coalesce(func.sum(_ADJUST_AMOUNT), 0),
        )
        .select_from(Transaction)
        .join(Transaction.restaurant)
        .where(*conditions, Transaction.voided_at.is_(None))
    ).one()
    return {"sum_charge": _int(row[0]), "sum_use": _int(row[1]), "sum_adjust": _int(row[2])}


def list_transactions(
    db: Session, conditions: Sequence[Any], limit: int = 50, offset: int = 0
) -> list[Transaction]:
    stmt = transaction_query(*conditions).limit(limit).offset(offset)
    return list(db.execute(stmt).unique().scalars().all())


def transaction_list_payload(
    db: Session, conditions: Sequence[Any], limit: int = 50, offset: int = 0
) -> dict[str, Any]:
    """TransactionListOut 모양의 dict (items + total + 합계)."""
    items = list_transactions(db, conditions, limit=limit, offset=offset)
    payload: dict[str, Any] = {
        "items": [serialize_transaction(t) for t in items],
        "total": count_transactions(db, *conditions),
        "limit": limit,
        "offset": offset,
    }
    payload.update(transaction_sums(db, *conditions))
    return payload


def recent_transactions(
    db: Session, restaurant_id: int, limit: int = 20, include_voided: bool = True
) -> list[Transaction]:
    conditions: list[Any] = [Transaction.restaurant_id == restaurant_id]
    if not include_voided:
        conditions.append(Transaction.voided_at.is_(None))
    return list(db.execute(transaction_query(*conditions).limit(limit)).unique().scalars().all())


def build_restaurant_detail(
    db: Session,
    restaurant: Restaurant,
    stats_row: Any = None,
    recent_limit: int = 20,
) -> dict[str, Any]:
    """RestaurantDetail 모양의 dict (최근 거래 포함)."""
    if stats_row is None:
        stats_row = stats_row_for(db, restaurant.id)
    detail = build_restaurant_summary(restaurant, stats_row)
    detail["recent_transactions"] = [
        serialize_transaction(t) for t in recent_transactions(db, restaurant.id, recent_limit)
    ]
    return detail


# ── 금액 검증 ─────────────────────────────────────────────────────


def validate_amount(tx_type: TxType | str, amount: Any) -> int:
    """CHARGE/USE 는 양수, ADJUST 는 0 이 아닌 값 (§0)."""
    try:
        value = int(amount)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="금액은 정수(원)로 입력해 주세요.",
        ) from None

    kind = tx_type.value if isinstance(tx_type, TxType) else str(tx_type)
    if kind == TxType.ADJUST.value:
        if value == 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="정정 금액은 0이 될 수 없습니다.",
            )
    elif value <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="금액은 0보다 커야 합니다.",
        )
    return value


def _as_tx_type(tx_type: TxType | str) -> TxType:
    if isinstance(tx_type, TxType):
        return tx_type
    try:
        return TxType(str(tx_type))
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="거래 유형이 올바르지 않습니다.",
        ) from None


# ── 거래 생성 / 취소 ──────────────────────────────────────────────


def create_transaction(
    db: Session,
    *,
    restaurant: Restaurant,
    type: TxType | str,
    amount: int,
    occurred_at: datetime | None = None,
    memo: str | None = None,
    receipt_id: int | None = None,
    actor: User | None = None,
    allow_negative: bool = False,
) -> tuple[Transaction, int, list[str]]:
    """거래 1건 생성. 반환: (거래, 생성 후 잔액, 경고 목록).

    커밋하지 않고 `flush()` 만 한다 — 호출자(라우터/confirm)가 커밋한다.
    """
    tx_type = _as_tx_type(type)
    value = validate_amount(tx_type, amount)

    current = balance_for(db, restaurant.id)
    signed = -value if tx_type == TxType.USE else value
    after = current + signed

    warnings: list[str] = []
    if tx_type == TxType.USE and after < 0:
        if not allow_negative:
            raise InsufficientBalance(current)
        warnings.append(NEGATIVE_BALANCE_WARNING)
    elif after < 0:
        # ADJUST 로 음수가 되는 경우는 막지 않되 경고는 남긴다
        warnings.append(NEGATIVE_BALANCE_WARNING)

    tx = Transaction(
        restaurant=restaurant,
        type=tx_type,
        amount=value,
        occurred_at=occurred_at or utc_now(),
        memo=memo,
        receipt_id=receipt_id,
    )
    if actor is not None:
        tx.creator = actor
        tx.created_by = actor.id
    db.add(tx)
    db.flush()  # 다음 잔액 계산이 이 INSERT 를 보게 하려면 필수
    return tx, after, warnings


def void_transaction(
    db: Session, tx: Transaction, actor: User | None = None, reason: str | None = None
) -> tuple[Transaction, int, list[str]]:
    """거래 취소(무효화). 삭제하지 않고 사유를 남긴다. 반환: (거래, 취소 후 잔액, 경고)."""
    if tx.voided_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="이미 취소된 거래입니다."
        )
    cleaned = (reason or "").strip()
    if not cleaned:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="취소 사유를 입력해 주세요.",
        )

    tx.voided_at = utc_now()
    tx.void_reason = cleaned
    if actor is not None:
        tx.voider = actor
        tx.voided_by = actor.id
    db.flush()

    after = balance_for(db, tx.restaurant_id)
    warnings: list[str] = []
    if after < 0:
        warnings.append(NEGATIVE_BALANCE_WARNING)
    return tx, after, warnings


# ── 중복 영수증 탐지 ──────────────────────────────────────────────


def find_duplicate_receipt(db: Session, receipt: Receipt) -> dict[str, Any] | None:
    """같은 사업자번호 + 합계금액 + 결제일시(±1일) 인 **이미 처리된** 영수증 찾기.

    차단하지 않고 경고만 한다 (§2.3).
    """
    bn = receipt.parsed_business_number
    amount = receipt.parsed_total_amount
    paid_at = receipt.parsed_paid_at
    if not bn or not amount or paid_at is None:
        return None

    other = (
        db.execute(
            select(Receipt)
            .where(
                Receipt.id != receipt.id,
                Receipt.consumed_at.is_not(None),
                Receipt.parsed_business_number == bn,
                Receipt.parsed_total_amount == amount,
                Receipt.parsed_paid_at >= paid_at - timedelta(days=1),
                Receipt.parsed_paid_at <= paid_at + timedelta(days=1),
            )
            .order_by(Receipt.consumed_at.desc())
        )
        .scalars()
        .first()
    )
    if other is None:
        return None

    tx = (
        db.execute(
            select(Transaction)
            .join(Transaction.restaurant)
            .options(contains_eager(Transaction.restaurant))
            .where(Transaction.receipt_id == other.id, Transaction.voided_at.is_(None))
            .order_by(Transaction.id.asc())
        )
        .unique()
        .scalars()
        .first()
    )
    restaurant_name = tx.restaurant.name if tx is not None and tx.restaurant else None
    where = f"{restaurant_name} · " if restaurant_name else ""
    return {
        "receipt_id": other.id,
        "transaction_id": tx.id if tx is not None else None,
        "restaurant_name": restaurant_name,
        "message": f"이미 처리한 영수증과 내용이 같습니다. ({where}{int(amount):,}원) 중복 등록이 아닌지 확인해 주세요.",
    }


# ── 영수증 확정 (원자 처리) ───────────────────────────────────────


def apply_parsed_to_receipt(receipt: Receipt, parsed: Any) -> None:
    """사용자가 화면에서 고친 값을 영수증에 반영한다 (사업자번호는 정규화)."""
    if parsed is None:
        return
    receipt.parsed_store_name = getattr(parsed, "store_name", None)
    receipt.parsed_business_number = normalize_business_number(
        getattr(parsed, "business_number", None)
    )
    receipt.parsed_address = getattr(parsed, "address", None)
    receipt.parsed_phone = getattr(parsed, "phone", None)
    total = getattr(parsed, "total_amount", None)
    receipt.parsed_total_amount = int(total) if total not in (None, "") else None
    receipt.parsed_paid_at = getattr(parsed, "paid_at", None)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=message
        )


def confirm_receipt(
    db: Session, receipt: Receipt, payload: ConfirmIn, actor: User | None = None
) -> dict[str, Any]:
    """영수증 확정 — 식당 생성 + CHARGE + USE 를 **하나의 트랜잭션**으로 처리.

    중간에 실패하면 전부 롤백하고 HTTP 에러를 그대로 올려보낸다.
    """
    # 같은 영수증으로 두 번 충전/차감되는 것을 막는다
    if receipt.consumed_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="이미 처리된 영수증입니다."
        )

    action = payload.action
    try:
        # 1) 사용자가 고친 parsed 값을 먼저 반영 (매칭·중복판정 기준도 이 값)
        if payload.parsed is not None:
            apply_parsed_to_receipt(receipt, payload.parsed)

        # 2) 식당 결정 (신규 등록 또는 기존 선택)
        if action == "register_and_charge":
            _require(payload.restaurant is not None, "등록할 식당 정보가 필요합니다.")
            info = payload.restaurant
            bn = normalize_business_number(info.business_number)
            if bn:
                existing = (
                    db.execute(select(Restaurant).where(Restaurant.business_number == bn))
                    .scalars()
                    .first()
                )
                if existing is not None:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=f"이미 등록된 사업자등록번호입니다. ({existing.name})",
                    )
            restaurant = Restaurant(
                name=info.name,
                business_number=bn,
                address=info.address,
                phone=info.phone,
                memo=info.memo,
                created_by=actor.id if actor is not None else None,
            )
            db.add(restaurant)
            db.flush()
        else:
            _require(payload.restaurant_id is not None, "식당을 선택해 주세요.")
            restaurant = db.get(Restaurant, int(payload.restaurant_id))
            if restaurant is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="식당을 찾을 수 없습니다."
                )

        balance_before = balance_for(db, restaurant.id)
        occurred_at = payload.occurred_at or receipt.parsed_paid_at or utc_now()
        memo = payload.memo

        created: list[Transaction] = []
        warnings: list[str] = []
        balance_after = balance_before

        # 3) CHARGE (선결제 충전)
        if action in ("register_and_charge", "charge"):
            _require(
                payload.charge_amount is not None and int(payload.charge_amount) > 0,
                "충전 금액을 입력해 주세요.",
            )
            tx, balance_after, warns = create_transaction(
                db,
                restaurant=restaurant,
                type=TxType.CHARGE,
                amount=int(payload.charge_amount),
                occurred_at=occurred_at,
                memo=memo,
                receipt_id=receipt.id,
                actor=actor,
                allow_negative=True,  # 충전은 잔액을 늘리므로 음수 검사 불필요
            )
            created.append(tx)
            warnings.extend(warns)

        # 4) USE (이번 결제에서 바로 사용한 금액) — 0/null 이면 만들지 않는다
        use_amount = int(payload.use_amount or 0)
        if action == "use":
            _require(use_amount > 0, "사용 금액을 입력해 주세요.")
        if use_amount > 0:
            tx, balance_after, warns = create_transaction(
                db,
                restaurant=restaurant,
                type=TxType.USE,
                amount=use_amount,
                occurred_at=occurred_at,
                memo=memo,
                receipt_id=receipt.id,
                actor=actor,
                allow_negative=payload.allow_negative,
            )
            created.append(tx)
            warnings.extend(warns)

        # 5) 영수증 소비 표시
        receipt.consumed_at = utc_now()
        db.flush()
        db.commit()
    except Exception:
        db.rollback()
        raise

    # 중복 경고는 dedup 없이 한 번만
    unique_warnings: list[str] = []
    for w in warnings:
        if w not in unique_warnings:
            unique_warnings.append(w)

    return {
        "restaurant": build_restaurant_detail(db, restaurant),
        "transactions": [serialize_transaction(t) for t in created],
        "balance_before": balance_before,
        "balance_after": balance_after,
        "warnings": unique_warnings,
    }


__all__ = [
    "INITIAL_BALANCE_MEMO",
    "InsufficientBalance",
    "NEGATIVE_BALANCE_WARNING",
    "balance_for",
    "balances_for_all",
    "build_restaurant_detail",
    "build_restaurant_summary",
    "build_summaries",
    "confirm_receipt",
    "count_transactions",
    "create_transaction",
    "find_duplicate_receipt",
    "list_transactions",
    "portfolio_totals",
    "recent_transactions",
    "restaurant_stats_subquery",
    "serialize_transaction",
    "stats_row_for",
    "stats_rows_for",
    "transaction_list_payload",
    "transaction_query",
    "transaction_sums",
    "user_brief",
    "validate_amount",
    "void_transaction",
]
