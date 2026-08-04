"""통계 / CSV 내보내기 — CONTRACT.md §2.4(export), §2.5.

통계는 전부 원장에서 파생되므로, 잔액 불변식이 그대로 성립해야 한다.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime

import pytest

from app.core.timeutil import KST
from tests.conftest import LOW_BALANCE_THRESHOLD

SUMMARY = "/api/stats/summary"
MONTHLY = "/api/stats/monthly"
EXPORT = "/api/transactions/export.csv"


def _kst_month_now() -> str:
    now = datetime.now(KST)
    return f"{now.year:04d}-{now.month:02d}"


# ══════════════════════════════════════════════════════════════════
#  /api/stats/summary
# ══════════════════════════════════════════════════════════════════
def test_summary_totals_match_the_ledger(admin_client, make_restaurant, make_tx):
    a = make_restaurant("통계식당A")
    b = make_restaurant("통계식당B")
    make_tx(a, "CHARGE", 300_000)
    make_tx(a, "USE", 120_000)
    make_tx(b, "CHARGE", 50_000)
    make_tx(b, "ADJUST", -5_000)

    body = admin_client.get(SUMMARY).json()

    assert body["restaurant_count"] == 2
    assert body["total_balance"] == (300_000 - 120_000) + (50_000 - 5_000) == 225_000
    assert body["all_time_charge"] == 350_000
    assert body["all_time_use"] == 120_000
    assert body["low_balance_threshold"] == LOW_BALANCE_THRESHOLD
    assert body["month"] == _kst_month_now()

    # 목록 API 의 total_balance 와도 일치해야 한다
    listing = admin_client.get("/api/restaurants").json()
    assert listing["total_balance"] == body["total_balance"]


def test_summary_excludes_voided(admin_client, make_restaurant, make_tx):
    r = make_restaurant("취소포함식당")
    make_tx(r, "CHARGE", 100_000)
    make_tx(r, "CHARGE", 999_000, voided=True, void_reason="오입력")
    make_tx(r, "USE", 888_000, voided=True, void_reason="오입력")

    body = admin_client.get(SUMMARY).json()
    assert body["total_balance"] == 100_000
    assert body["all_time_charge"] == 100_000
    assert body["all_time_use"] == 0


def test_summary_month_figures_cover_current_kst_month(admin_client, make_restaurant, make_tx):
    r = make_restaurant("이번달식당")
    make_tx(r, "CHARGE", 200_000)  # 기본 occurred_at = now → 이번 달
    make_tx(r, "USE", 30_000)
    make_tx(r, "CHARGE", 500_000, days_ago=400)  # 작년 → 이번 달 집계에서 제외
    make_tx(r, "USE", 70_000, days_ago=400)

    body = admin_client.get(SUMMARY).json()
    assert body["month"] == _kst_month_now()
    assert body["month_charge"] == 200_000
    assert body["month_use"] == 30_000
    assert body["all_time_charge"] == 700_000
    assert body["all_time_use"] == 100_000


def test_summary_low_balance_count_respects_threshold(admin_client, make_restaurant, make_tx):
    low = make_restaurant("잔액부족식당")
    make_tx(low, "CHARGE", LOW_BALANCE_THRESHOLD - 1)

    boundary = make_restaurant("경계식당")
    make_tx(boundary, "CHARGE", LOW_BALANCE_THRESHOLD)

    plenty = make_restaurant("여유식당")
    make_tx(plenty, "CHARGE", 500_000)

    negative = make_restaurant("외상식당")
    make_tx(negative, "CHARGE", 10_000)
    make_tx(negative, "USE", 25_000)

    body = admin_client.get(SUMMARY).json()
    assert body["restaurant_count"] == 4
    assert body["low_balance_count"] == 2, "임계값 '미만'만 (음수 포함, 같으면 제외)"

    names = {r["name"] for r in body["low_balance_restaurants"]}
    assert names == {"잔액부족식당", "외상식당"}
    assert all(r["is_low_balance"] for r in body["low_balance_restaurants"])


def test_summary_low_balance_list_is_capped_at_five(admin_client, make_restaurant, make_tx):
    for i in range(8):
        r = make_restaurant(f"부족식당{i}")
        make_tx(r, "CHARGE", 1_000 + i)

    body = admin_client.get(SUMMARY).json()
    assert body["low_balance_count"] == 8
    assert len(body["low_balance_restaurants"]) == 5, "목록은 5건 (§2.5)"


def test_summary_recent_transactions_capped_at_ten(admin_client, make_restaurant, make_tx):
    r = make_restaurant("최근거래식당")
    for i in range(14):
        make_tx(r, "CHARGE", 1_000, days_ago=i)

    body = admin_client.get(SUMMARY).json()
    assert len(body["recent_transactions"]) == 10, "최근 10건 (§2.5)"
    # 최신순
    occurred = [t["occurred_at"] for t in body["recent_transactions"]]
    assert occurred == sorted(occurred, reverse=True)


def test_summary_on_empty_database(admin_client):
    body = admin_client.get(SUMMARY).json()
    assert body["total_balance"] == 0
    assert body["restaurant_count"] == 0
    assert body["low_balance_count"] == 0
    assert body["recent_transactions"] == []
    assert body["low_balance_restaurants"] == []


def test_summary_requires_auth(client):
    assert client.get(SUMMARY).status_code == 401


# ══════════════════════════════════════════════════════════════════
#  /api/stats/monthly
# ══════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("months", [1, 3, 6, 12])
def test_monthly_returns_requested_bucket_count_in_order(admin_client, months):
    body = admin_client.get(MONTHLY, params={"months": months}).json()
    items = body["items"]

    assert len(items) == months, f"months={months} 개의 버킷"
    keys = [i["month"] for i in items]
    assert keys == sorted(keys), "오래된 달 → 최근 달 순 (§2.5)"
    assert len(set(keys)) == months, "중복 없는 달"
    assert keys[-1] == _kst_month_now(), "마지막 버킷은 이번 달(KST)"
    assert all(re.fullmatch(r"\d{4}-\d{2}", k) for k in keys)


def test_monthly_net_is_charge_minus_use(admin_client, make_restaurant, make_tx):
    r = make_restaurant("월별식당")
    make_tx(r, "CHARGE", 300_000)
    make_tx(r, "USE", 120_000)
    make_tx(r, "CHARGE", 90_000, voided=True, void_reason="오입력")

    items = admin_client.get(MONTHLY, params={"months": 2}).json()["items"]
    current = items[-1]

    assert current["month"] == _kst_month_now()
    assert current["charge"] == 300_000, "void 제외"
    assert current["use"] == 120_000
    assert current["net"] == 180_000
    for point in items:
        assert point["net"] == point["charge"] - point["use"]


def test_monthly_empty_months_are_zero_filled(admin_client, make_restaurant, make_tx):
    r = make_restaurant("빈달식당")
    make_tx(r, "CHARGE", 100_000)

    items = admin_client.get(MONTHLY, params={"months": 6}).json()["items"]
    assert len(items) == 6
    for point in items[:-1]:
        assert point["charge"] == 0 and point["use"] == 0 and point["net"] == 0


def test_monthly_rejects_out_of_range(admin_client):
    assert admin_client.get(MONTHLY, params={"months": 0}).status_code == 422
    assert admin_client.get(MONTHLY, params={"months": 999}).status_code == 422


# ══════════════════════════════════════════════════════════════════
#  /api/stats/by-restaurant, /api/stats/by-user
# ══════════════════════════════════════════════════════════════════
def test_by_restaurant_rows_match_ledger(admin_client, make_restaurant, make_tx):
    a = make_restaurant("식당별A")
    b = make_restaurant("식당별B")
    make_tx(a, "CHARGE", 300_000)
    make_tx(a, "USE", 120_000)
    make_tx(b, "CHARGE", 50_000)

    rows = {r["name"]: r for r in admin_client.get("/api/stats/by-restaurant").json()["items"]}
    assert rows["식당별A"]["charge"] == 300_000
    assert rows["식당별A"]["use"] == 120_000
    assert rows["식당별A"]["balance"] == 180_000
    assert rows["식당별B"]["balance"] == 50_000


def test_by_user_attributes_transactions(admin_client, make_restaurant):
    r = make_restaurant("사용자별식당")
    admin_client.post(
        "/api/transactions", json={"restaurant_id": r.id, "type": "CHARGE", "amount": 100_000}
    )
    admin_client.post(
        "/api/transactions", json={"restaurant_id": r.id, "type": "USE", "amount": 40_000}
    )

    rows = admin_client.get("/api/stats/by-user").json()["items"]
    mine = next(row for row in rows if row["user_id"] == admin_client.user["id"])
    assert mine["charge"] == 100_000
    assert mine["use"] == 40_000
    assert mine["tx_count"] == 2


# ══════════════════════════════════════════════════════════════════
#  CSV 내보내기 (UTF-8 BOM)
# ══════════════════════════════════════════════════════════════════
def _read_csv(resp):
    text = resp.content.decode("utf-8-sig")
    rows = [row for row in csv.reader(io.StringIO(text)) if row]
    return rows[0], rows[1:]


def test_csv_export_has_utf8_bom_and_header(admin_client, make_restaurant, make_tx):
    r = make_restaurant("내보내기식당", business_number="6011000044")
    make_tx(r, "CHARGE", 100_000, memo="선결제 10만원")
    make_tx(r, "USE", 23_000, memo="점심 2인")

    resp = admin_client.get(EXPORT)
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/csv")

    # 엑셀에서 한글이 깨지지 않게 UTF-8 BOM 으로 시작해야 한다 (§2.4)
    assert resp.content.startswith(b"\xef\xbb\xbf"), "UTF-8 BOM 누락"

    disposition = resp.headers.get("content-disposition", "")
    assert re.search(r"transactions_\d{8}\.csv", disposition), disposition

    header, rows = _read_csv(resp)
    # CONTRACT 는 컬럼 문구를 못 박지 않았으므로, 필수 개념이 있는지만 본다
    for column in ("일시", "식당", "유형", "금액", "메모"):
        assert column in header, f"헤더에 '{column}' 이 없다: {header}"
    assert len(rows) == 2
    assert all(len(row) == len(header) for row in rows)


def test_csv_export_content_reflects_transactions(admin_client, make_restaurant, make_tx):
    r = make_restaurant("내용검증식당", business_number="6011000043")
    make_tx(r, "CHARGE", 100_000, memo="선결제 10만원")
    make_tx(r, "USE", 23_000, memo="점심 2인")

    resp = admin_client.get(EXPORT)
    header, rows = _read_csv(resp)
    text = resp.content.decode("utf-8-sig")

    assert "내용검증식당" in text
    assert "선결제 10만원" in text and "점심 2인" in text
    # §5.7 문구와 동일한 한국어 라벨
    assert "선결제 충전" in text and "사용" in text

    amount_col = header.index("금액")
    assert {row[amount_col] for row in rows} == {"100000", "23000"}


def test_csv_export_respects_filters(admin_client, make_restaurant, make_tx):
    a = make_restaurant("필터식당A")
    b = make_restaurant("필터식당B")
    make_tx(a, "CHARGE", 100_000)
    make_tx(b, "CHARGE", 200_000)

    resp = admin_client.get(EXPORT, params={"restaurant_id": a.id})
    _, rows = _read_csv(resp)
    assert len(rows) == 1

    text = resp.content.decode("utf-8-sig")
    assert "필터식당A" in text
    assert "필터식당B" not in text


def test_csv_export_with_no_rows_still_has_header(admin_client):
    resp = admin_client.get(EXPORT)
    assert resp.status_code == 200
    assert resp.content.startswith(b"\xef\xbb\xbf")

    header, rows = _read_csv(resp)
    assert header
    assert rows == []


def test_csv_export_requires_auth(client):
    assert client.get(EXPORT).status_code == 401
