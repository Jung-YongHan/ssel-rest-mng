"""원장 / 잔액 규약 — CONTRACT.md §0, §2.4.

    balance = Σ CHARGE − Σ USE + Σ ADJUST    (voided 제외)

잔액은 저장하지 않고 항상 계산한다는 것이 이 앱의 핵심 불변식이다.
순수 계산은 모델/SQL 로, 나머지는 HTTP API 로 검증한다.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.core.timeutil import utc_now
from app.models import SIGNED_AMOUNT_SQL, Transaction, TxType

TX_URL = "/api/transactions"


# ══════════════════════════════════════════════════════════════════
#  순수 계산 (DB/HTTP 없이)
# ══════════════════════════════════════════════════════════════════
def test_signed_amount_property():
    assert Transaction(type=TxType.CHARGE, amount=10_000).signed_amount == 10_000
    assert Transaction(type=TxType.USE, amount=3_000).signed_amount == -3_000
    assert Transaction(type=TxType.ADJUST, amount=-500).signed_amount == -500
    assert Transaction(type=TxType.ADJUST, amount=500).signed_amount == 500


def test_voided_transaction_contributes_zero():
    tx = Transaction(type=TxType.CHARGE, amount=10_000, voided_at=utc_now())
    assert tx.is_voided is True
    assert tx.signed_amount == 0

    used = Transaction(type=TxType.USE, amount=10_000, voided_at=utc_now())
    assert used.signed_amount == 0


def test_not_voided_transaction_is_not_flagged():
    tx = Transaction(type=TxType.USE, amount=1_000)
    assert tx.is_voided is False


# ══════════════════════════════════════════════════════════════════
#  SQL 집계식 (SIGNED_AMOUNT_SQL) — 목록/통계가 모두 이걸 쓴다
# ══════════════════════════════════════════════════════════════════
def _db_balance(db, restaurant_id: int) -> int:
    return int(
        db.scalar(
            select(func.coalesce(func.sum(SIGNED_AMOUNT_SQL), 0)).where(
                Transaction.restaurant_id == restaurant_id,
                Transaction.voided_at.is_(None),
            )
        )
        or 0
    )


def test_sql_balance_is_charge_minus_use_plus_adjust(db, make_restaurant, make_tx):
    r = make_restaurant("원장식당")
    make_tx(r, "CHARGE", 300_000)
    make_tx(r, "CHARGE", 200_000)
    make_tx(r, "USE", 120_000)
    make_tx(r, "USE", 30_000)
    make_tx(r, "ADJUST", -5_000)
    make_tx(r, "ADJUST", 2_000)

    expected = (300_000 + 200_000) - (120_000 + 30_000) + (-5_000 + 2_000)
    assert _db_balance(db, r.id) == expected == 347_000


def test_sql_balance_excludes_voided(db, make_restaurant, make_tx):
    r = make_restaurant("취소포함식당")
    make_tx(r, "CHARGE", 100_000)
    make_tx(r, "CHARGE", 500_000, voided=True, void_reason="금액 오입력")
    make_tx(r, "USE", 20_000)
    make_tx(r, "USE", 90_000, voided=True, void_reason="중복 기록")
    make_tx(r, "ADJUST", -7_000, voided=True, void_reason="잘못된 정정")

    assert _db_balance(db, r.id) == 80_000


def test_sql_balance_can_be_negative(db, make_restaurant, make_tx):
    r = make_restaurant("음수식당")
    make_tx(r, "CHARGE", 10_000)
    make_tx(r, "USE", 25_000)
    assert _db_balance(db, r.id) == -15_000


# ══════════════════════════════════════════════════════════════════
#  HTTP API — 거래 생성
# ══════════════════════════════════════════════════════════════════
def _create(client, restaurant, tx_type, amount, **extra):
    payload = {
        "restaurant_id": restaurant if isinstance(restaurant, int) else restaurant.id,
        "type": tx_type,
        "amount": amount,
    }
    payload.update(extra)
    return client.post(TX_URL, json=payload)


def test_api_balance_matches_ledger_sum(admin_client, make_restaurant):
    r = make_restaurant("API원장식당")
    assert _create(admin_client, r, "CHARGE", 300_000).status_code == 201
    assert _create(admin_client, r, "USE", 120_000).status_code == 201
    last = _create(admin_client, r, "ADJUST", -5_000)
    assert last.status_code == 201
    assert last.json()["balance_after"] == 175_000

    detail = admin_client.get(f"/api/restaurants/{r.id}").json()
    assert detail["balance"] == 175_000
    assert detail["charge_total"] == 300_000
    assert detail["use_total"] == 120_000
    assert detail["tx_count"] == 3


def test_transaction_out_shape(admin_client, make_restaurant):
    r = make_restaurant("형태식당")
    body = _create(admin_client, r, "CHARGE", 50_000, memo="선결제 5만원").json()

    assert set(body) == {"transaction", "balance_after", "warnings"}
    tx = body["transaction"]
    assert tx["restaurant_id"] == r.id
    assert tx["restaurant_name"] == "형태식당"
    assert tx["type"] == "CHARGE"
    assert tx["amount"] == 50_000
    assert tx["signed_amount"] == 50_000
    assert tx["memo"] == "선결제 5만원"
    assert tx["is_voided"] is False
    assert tx["voided_at"] is None and tx["void_reason"] is None
    assert tx["has_receipt"] is False and tx["receipt_id"] is None
    assert tx["created_by"]["email"] == admin_client.user["email"]
    assert tx["occurred_at"].endswith("+00:00"), "응답 시간은 aware ISO (§0)"


def test_use_signed_amount_is_negative(admin_client, make_restaurant):
    r = make_restaurant("차감식당")
    _create(admin_client, r, "CHARGE", 100_000)
    tx = _create(admin_client, r, "USE", 30_000).json()["transaction"]
    assert tx["amount"] == 30_000, "amount 는 항상 원본 (양수)"
    assert tx["signed_amount"] == -30_000, "signed_amount 만 부호를 가진다"


# ── 음수 잔액 가드 ────────────────────────────────────────────────
def test_use_over_balance_conflicts_then_succeeds_with_allow_negative(
    admin_client, make_restaurant
):
    r = make_restaurant("잔액부족식당")
    _create(admin_client, r, "CHARGE", 50_000)

    blocked = _create(admin_client, r, "USE", 80_000)
    assert blocked.status_code == 409
    assert "잔액이 부족" in blocked.json()["detail"]

    # 거부됐으므로 잔액은 그대로
    assert admin_client.get(f"/api/restaurants/{r.id}").json()["balance"] == 50_000

    allowed = _create(admin_client, r, "USE", 80_000, allow_negative=True)
    assert allowed.status_code == 201, allowed.text
    assert allowed.json()["balance_after"] == -30_000
    assert allowed.json()["warnings"], "음수가 됐으면 경고 문구가 있어야 한다"
    assert admin_client.get(f"/api/restaurants/{r.id}").json()["balance"] == -30_000


def test_use_exactly_to_zero_is_allowed(admin_client, make_restaurant):
    r = make_restaurant("정확히0식당")
    _create(admin_client, r, "CHARGE", 40_000)
    resp = _create(admin_client, r, "USE", 40_000)
    assert resp.status_code == 201, "0 은 음수가 아니므로 통과해야 한다"
    assert resp.json()["balance_after"] == 0


def test_charge_never_needs_allow_negative(admin_client, make_restaurant):
    r = make_restaurant("충전식당")
    assert _create(admin_client, r, "CHARGE", 1_000_000).status_code == 201


# ── 금액 검증 ─────────────────────────────────────────────────────
@pytest.mark.parametrize("tx_type", ["CHARGE", "USE", "ADJUST"])
def test_amount_zero_is_rejected(admin_client, make_restaurant, tx_type):
    r = make_restaurant()
    resp = _create(admin_client, r, tx_type, 0)
    assert resp.status_code == 422, f"{tx_type} amount=0 은 거부 (§0)"


@pytest.mark.parametrize("tx_type", ["CHARGE", "USE"])
def test_negative_amount_rejected_for_charge_and_use(admin_client, make_restaurant, tx_type):
    r = make_restaurant()
    resp = _create(admin_client, r, tx_type, -1_000)
    assert resp.status_code == 422, "CHARGE/USE 는 양수만 (§2.4)"


def test_adjust_accepts_both_signs(admin_client, make_restaurant):
    r = make_restaurant("정정식당")
    _create(admin_client, r, "CHARGE", 100_000)

    down = _create(admin_client, r, "ADJUST", -15_000, memo="사장님 장부와 차이 정정")
    assert down.status_code == 201, down.text
    assert down.json()["balance_after"] == 85_000
    assert down.json()["transaction"]["signed_amount"] == -15_000

    up = _create(admin_client, r, "ADJUST", 5_000, memo="반대로 정정")
    assert up.status_code == 201
    assert up.json()["balance_after"] == 90_000

    assert admin_client.get(f"/api/restaurants/{r.id}").json()["balance"] == 90_000


def test_transaction_on_unknown_restaurant_is_404(admin_client):
    resp = _create(admin_client, 999_999, "CHARGE", 10_000)
    assert resp.status_code == 404


def test_transaction_create_requires_auth(client, make_restaurant):
    r = make_restaurant()
    assert _create(client, r, "CHARGE", 10_000).status_code == 401


# ══════════════════════════════════════════════════════════════════
#  void (기록 취소)
# ══════════════════════════════════════════════════════════════════
def test_void_requires_a_reason(admin_client, make_restaurant):
    r = make_restaurant("사유필요식당")
    tx_id = _create(admin_client, r, "CHARGE", 100_000).json()["transaction"]["id"]

    assert admin_client.post(f"{TX_URL}/{tx_id}/void", json={}).status_code == 422
    assert admin_client.post(f"{TX_URL}/{tx_id}/void", json={"reason": ""}).status_code == 422
    # 아직 취소되지 않았다
    assert admin_client.get(f"/api/restaurants/{r.id}").json()["balance"] == 100_000


def test_void_removes_amount_from_balance_and_records_who(admin_client, make_restaurant):
    r = make_restaurant("취소식당")
    tx_id = _create(admin_client, r, "CHARGE", 100_000).json()["transaction"]["id"]

    resp = admin_client.post(f"{TX_URL}/{tx_id}/void", json={"reason": "금액 오입력"})
    assert resp.status_code == 200, resp.text

    body = resp.json()
    assert body["balance_after"] == 0
    tx = body["transaction"]
    assert tx["is_voided"] is True
    assert tx["void_reason"] == "금액 오입력"
    assert tx["voided_at"] is not None
    assert tx["voided_by"]["email"] == admin_client.user["email"]
    assert tx["signed_amount"] == 0, "void 면 signed_amount 는 0 (§2.4)"
    assert tx["amount"] == 100_000, "원본 amount 는 보존한다"

    assert admin_client.get(f"/api/restaurants/{r.id}").json()["balance"] == 0


def test_second_void_conflicts(admin_client, make_restaurant):
    r = make_restaurant("이중취소식당")
    tx_id = _create(admin_client, r, "CHARGE", 100_000).json()["transaction"]["id"]

    assert admin_client.post(f"{TX_URL}/{tx_id}/void", json={"reason": "첫 취소"}).status_code == 200
    again = admin_client.post(f"{TX_URL}/{tx_id}/void", json={"reason": "두 번째 취소"})
    assert again.status_code == 409, "이미 void 면 409 (§2.4)"


def test_void_of_use_restores_balance(admin_client, make_restaurant):
    r = make_restaurant("사용취소식당")
    _create(admin_client, r, "CHARGE", 100_000)
    use_id = _create(admin_client, r, "USE", 40_000).json()["transaction"]["id"]
    assert admin_client.get(f"/api/restaurants/{r.id}").json()["balance"] == 60_000

    resp = admin_client.post(f"{TX_URL}/{use_id}/void", json={"reason": "잘못 기록"})
    assert resp.status_code == 200
    assert resp.json()["balance_after"] == 100_000


def test_void_of_unknown_transaction_is_404(admin_client):
    assert admin_client.post(f"{TX_URL}/999999/void", json={"reason": "없음"}).status_code == 404


def test_member_can_void_but_is_recorded(member_client, make_restaurant):
    """void 는 누구나 가능하되 누가 했는지 기록된다 (§2.4)."""
    r = make_restaurant("구성원취소식당")
    tx_id = _create(member_client, r, "CHARGE", 50_000).json()["transaction"]["id"]

    resp = member_client.post(f"{TX_URL}/{tx_id}/void", json={"reason": "구성원이 취소"})
    assert resp.status_code == 200
    assert resp.json()["transaction"]["voided_by"]["email"] == member_client.user["email"]


# ══════════════════════════════════════════════════════════════════
#  목록 집계 (sum_charge / sum_use / sum_adjust)
# ══════════════════════════════════════════════════════════════════
def test_transaction_list_sums_exclude_voided(admin_client, make_restaurant, make_tx):
    r = make_restaurant("합계식당")
    make_tx(r, "CHARGE", 300_000)
    make_tx(r, "USE", 120_000)
    make_tx(r, "ADJUST", -5_000)
    make_tx(r, "CHARGE", 999_000, voided=True, void_reason="취소됨")

    body = admin_client.get(TX_URL, params={"restaurant_id": r.id}).json()
    assert body["total"] == 4, "void 도 목록에는 보인다 (include_voided 기본 true)"
    assert body["sum_charge"] == 300_000
    assert body["sum_use"] == 120_000
    assert body["sum_adjust"] == -5_000
    assert body["limit"] == 50 and body["offset"] == 0

    excluded = admin_client.get(
        TX_URL, params={"restaurant_id": r.id, "include_voided": False}
    ).json()
    assert excluded["total"] == 3


def test_transaction_list_filters_by_type(admin_client, make_restaurant, make_tx):
    r = make_restaurant("타입필터식당")
    make_tx(r, "CHARGE", 100_000)
    make_tx(r, "USE", 10_000)
    make_tx(r, "USE", 20_000)

    only_use = admin_client.get(TX_URL, params={"restaurant_id": r.id, "type": "USE"}).json()
    assert only_use["total"] == 2
    assert {t["type"] for t in only_use["items"]} == {"USE"}
    assert only_use["sum_use"] == 30_000


def test_restaurant_scoped_transaction_list(admin_client, make_restaurant, make_tx):
    a = make_restaurant("A식당")
    b = make_restaurant("B식당")
    make_tx(a, "CHARGE", 100_000)
    make_tx(b, "CHARGE", 200_000)

    body = admin_client.get(f"/api/restaurants/{a.id}/transactions").json()
    assert body["total"] == 1
    assert body["items"][0]["restaurant_id"] == a.id
