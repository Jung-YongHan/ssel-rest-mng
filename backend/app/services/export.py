"""CSV 내보내기 — Excel 에서 한글이 깨지지 않도록 **UTF-8 BOM(utf-8-sig)** 으로 쓴다."""

from __future__ import annotations

import csv
from collections.abc import Iterable
from datetime import datetime
from io import StringIO

from app.core.timeutil import kst_today, to_kst
from app.models import Transaction, TxType
from app.services.matching import format_business_number

CSV_COLUMNS = [
    "일시",
    "식당",
    "사업자등록번호",
    "유형",
    "금액",
    "부호금액",
    "메모",
    "작성자",
    "영수증",
    "취소여부",
    "취소사유",
]

# 프론트 `txLabel` 과 동일한 문구를 쓴다 (§5.7)
TYPE_LABELS = {
    TxType.CHARGE.value: "선결제 충전",
    TxType.USE.value: "사용",
    TxType.ADJUST.value: "정정",
}


def _kst_text(dt: datetime | None) -> str:
    """CSV 는 사람이 읽는 문서이므로 KST 벽시계로 렌더한다."""
    kst = to_kst(dt)
    return kst.strftime("%Y-%m-%d %H:%M") if kst else ""


def _type_label(tx_type: TxType | str) -> str:
    key = tx_type.value if isinstance(tx_type, TxType) else str(tx_type)
    return TYPE_LABELS.get(key, key)


def transaction_row(tx: Transaction) -> list[str | int]:
    restaurant = tx.restaurant
    return [
        _kst_text(tx.occurred_at),
        restaurant.name if restaurant is not None else "",
        format_business_number(restaurant.business_number) if restaurant is not None else "",
        _type_label(tx.type),
        int(tx.amount),
        int(tx.signed_amount),
        tx.memo or "",
        tx.creator.name if tx.creator is not None else "",
        tx.receipt_id if tx.receipt_id is not None else "",
        "취소" if tx.is_voided else "정상",
        tx.void_reason or "",
    ]


def transactions_csv(transactions: Iterable[Transaction]) -> bytes:
    """거래 목록 → CSV 바이트 (UTF-8 BOM)."""
    buffer = StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(CSV_COLUMNS)
    for tx in transactions:
        writer.writerow(transaction_row(tx))
    return buffer.getvalue().encode("utf-8-sig")


def csv_filename(prefix: str = "transactions") -> str:
    """`transactions_YYYYMMDD.csv` (KST 기준 오늘)."""
    return f"{prefix}_{kst_today().strftime('%Y%m%d')}.csv"


__all__ = ["CSV_COLUMNS", "TYPE_LABELS", "csv_filename", "transaction_row", "transactions_csv"]
