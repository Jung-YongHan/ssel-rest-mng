"""식당 CRUD / 목록 — CONTRACT.md §2.2.

특히 **이미 선결제해둔 식당 백필**(`initial_balance`) 이 CHARGE 거래 한 건으로
정확히 표현되는지, 목록 집계가 원장과 일치하는지를 본다.
"""

from __future__ import annotations

from tests.conftest import LOW_BALANCE_THRESHOLD

URL = "/api/restaurants"


def _create(client, **body):
    return client.post(URL, json=body)


def _names(listing: dict) -> list[str]:
    return [r["name"] for r in listing["items"]]


# ══════════════════════════════════════════════════════════════════
#  생성
# ══════════════════════════════════════════════════════════════════
def test_create_with_initial_balance_makes_exactly_one_charge(admin_client):
    resp = _create(
        admin_client,
        name="초기잔액식당",
        business_number="123-45-67890",
        address="전북 전주시 덕진구 백제대로 1",
        phone="063-100-1001",
        memo="앱 도입 전 선결제해둔 곳",
        initial_balance=250_000,
    )
    assert resp.status_code == 201, resp.text

    body = resp.json()
    assert body["name"] == "초기잔액식당"
    assert body["business_number"] == "1234567890", "숫자 10자리로 정규화 저장 (§0)"
    assert body["balance"] == 250_000
    assert body["charge_total"] == 250_000
    assert body["use_total"] == 0
    assert body["tx_count"] == 1
    assert body["is_archived"] is False
    assert body["is_low_balance"] is False

    txs = body["recent_transactions"]
    assert len(txs) == 1, "initial_balance 는 CHARGE 거래를 정확히 한 건만 만든다"
    assert txs[0]["type"] == "CHARGE"
    assert txs[0]["amount"] == 250_000
    assert txs[0]["memo"], "기본 메모('초기 잔액 등록')가 붙어야 한다"

    # 목록에 보이는 잔액도 같아야 한다
    listing = admin_client.get(URL).json()
    row = next(r for r in listing["items"] if r["id"] == body["id"])
    assert row["balance"] == 250_000
    assert row["last_charged_at"] is not None


def test_create_with_custom_initial_balance_memo(admin_client):
    body = _create(
        admin_client,
        name="메모지정식당",
        initial_balance=100_000,
        initial_balance_memo="2026년 3월 현금 선결제",
    ).json()
    assert body["recent_transactions"][0]["memo"] == "2026년 3월 현금 선결제"


def test_create_without_initial_balance_has_no_transaction(admin_client):
    body = _create(admin_client, name="잔액0식당").json()
    assert body["balance"] == 0
    assert body["tx_count"] == 0
    assert body["recent_transactions"] == []
    assert body["is_low_balance"] is True, "0원은 임계값 미만이므로 잔액 부족"


def test_create_allows_null_business_number(admin_client):
    """수동 등록 시 사업자번호를 모를 수 있다 (NULL 은 중복 허용)."""
    assert _create(admin_client, name="번호없음식당1").status_code == 201
    assert _create(admin_client, name="번호없음식당2").status_code == 201


def test_duplicate_business_number_conflicts(admin_client):
    assert _create(admin_client, name="먼저식당", business_number="1112233333").status_code == 201

    resp = _create(admin_client, name="나중식당", business_number="111-22-33333")
    assert resp.status_code == 409, "하이픈 유무와 무관하게 중복 판정 (§2.2)"
    assert "먼저식당" in resp.json()["detail"], "기존 식당 이름을 알려줘야 한다"


def test_create_rejects_empty_name(admin_client):
    assert _create(admin_client, name="").status_code == 422
    assert _create(admin_client, name="가" * 201).status_code == 422


def test_create_rejects_negative_initial_balance(admin_client):
    assert _create(admin_client, name="음수초기식당", initial_balance=-1).status_code == 422


def test_create_requires_auth(client):
    assert _create(client, name="비인증식당").status_code == 401


def test_list_requires_auth(client):
    assert client.get(URL).status_code == 401


# ══════════════════════════════════════════════════════════════════
#  목록 — 정렬 / 검색 / 집계
# ══════════════════════════════════════════════════════════════════
def test_list_sorting_by_balance(admin_client):
    for name, balance in (("소액식당", 10_000), ("고액식당", 300_000), ("중간식당", 50_000)):
        _create(admin_client, name=name, initial_balance=balance)

    desc = admin_client.get(URL, params={"sort": "balance_desc"}).json()
    assert [r["balance"] for r in desc["items"]] == [300_000, 50_000, 10_000]
    assert _names(desc) == ["고액식당", "중간식당", "소액식당"]

    asc = admin_client.get(URL, params={"sort": "balance_asc"}).json()
    assert [r["balance"] for r in asc["items"]] == [10_000, 50_000, 300_000]

    # 기본 정렬은 balance_desc
    default = admin_client.get(URL).json()
    assert [r["balance"] for r in default["items"]] == [300_000, 50_000, 10_000]


def test_list_sorting_by_name(admin_client):
    for name in ("행복분식", "든든한식당", "청춘국수"):
        _create(admin_client, name=name)
    body = admin_client.get(URL, params={"sort": "name"}).json()
    assert _names(body) == sorted(_names(body))


def test_query_search_by_name(admin_client):
    _create(admin_client, name="행복분식", business_number="6011000011")
    _create(admin_client, name="청춘국수", business_number="6011000022")

    body = admin_client.get(URL, params={"query": "행복"}).json()
    assert _names(body) == ["행복분식"]

    nothing = admin_client.get(URL, params={"query": "존재하지않는이름"}).json()
    assert nothing["items"] == []


def test_query_search_by_address(admin_client):
    _create(admin_client, name="주소식당", address="전북 전주시 덕진구 명륜3길 45")
    _create(admin_client, name="다른식당", address="서울 관악구 관악로 1")

    body = admin_client.get(URL, params={"query": "덕진구"}).json()
    assert _names(body) == ["주소식당"]


def test_query_search_by_business_number(admin_client):
    _create(admin_client, name="행복분식", business_number="6011000011")
    _create(admin_client, name="청춘국수", business_number="6011000022")

    # 숫자만 입력
    digits = admin_client.get(URL, params={"query": "6011000022"}).json()
    assert _names(digits) == ["청춘국수"]

    # 하이픈 포함으로 입력해도 찾아야 한다 (§2.2)
    hyphened = admin_client.get(URL, params={"query": "601-10-00011"}).json()
    assert _names(hyphened) == ["행복분식"]


def test_total_balance_equals_sum_of_items(admin_client):
    balances = [120_000, 45_000, 5_000]
    for i, balance in enumerate(balances):
        _create(admin_client, name=f"합계식당{i}", initial_balance=balance)

    body = admin_client.get(URL).json()
    assert set(body) == {
        "items",
        "total",
        "total_balance",
        "low_balance_count",
        "low_balance_threshold",
    }
    assert body["total"] == 3
    assert body["total_balance"] == sum(balances)
    assert body["total_balance"] == sum(r["balance"] for r in body["items"])


def test_low_balance_flags_and_count(admin_client):
    _create(admin_client, name="여유식당", initial_balance=500_000)
    _create(admin_client, name="경계식당", initial_balance=LOW_BALANCE_THRESHOLD)
    _create(admin_client, name="부족식당", initial_balance=LOW_BALANCE_THRESHOLD - 1)

    body = admin_client.get(URL).json()
    assert body["low_balance_threshold"] == LOW_BALANCE_THRESHOLD
    assert body["low_balance_count"] == 1, "임계값 '미만'만 부족 (같으면 아님)"

    flags = {r["name"]: r["is_low_balance"] for r in body["items"]}
    assert flags == {"여유식당": False, "경계식당": False, "부족식당": True}

    only_low = admin_client.get(URL, params={"low_only": True}).json()
    assert _names(only_low) == ["부족식당"]


def test_negative_balance_counts_as_low(admin_client, make_restaurant, make_tx):
    r = make_restaurant("외상식당")
    make_tx(r, "CHARGE", 10_000)
    make_tx(r, "USE", 25_000)

    body = admin_client.get(URL).json()
    row = next(x for x in body["items"] if x["id"] == r.id)
    assert row["balance"] == -15_000
    assert row["is_low_balance"] is True
    assert body["low_balance_count"] == 1


def test_list_aggregates_match_ledger(admin_client, make_restaurant, make_tx):
    r = make_restaurant("집계검증식당")
    make_tx(r, "CHARGE", 300_000)
    make_tx(r, "CHARGE", 100_000)
    make_tx(r, "USE", 120_000)
    make_tx(r, "CHARGE", 999_000, voided=True, void_reason="오입력")

    row = next(x for x in admin_client.get(URL).json()["items"] if x["id"] == r.id)
    assert row["charge_total"] == 400_000, "void 는 집계에서 빠진다"
    assert row["use_total"] == 120_000
    assert row["balance"] == 280_000
    assert row["tx_count"] == 3
    assert row["last_used_at"] is not None
    assert row["last_charged_at"] is not None


# ══════════════════════════════════════════════════════════════════
#  상세 / 수정
# ══════════════════════════════════════════════════════════════════
def test_detail_includes_recent_transactions(admin_client, make_restaurant, make_tx):
    r = make_restaurant("상세식당")
    make_tx(r, "CHARGE", 200_000, days_ago=10)
    make_tx(r, "USE", 30_000, days_ago=1)

    body = admin_client.get(f"{URL}/{r.id}").json()
    assert body["id"] == r.id
    assert len(body["recent_transactions"]) == 2
    assert body["balance"] == 170_000


def test_detail_of_unknown_restaurant_is_404(admin_client):
    assert admin_client.get(f"{URL}/999999").status_code == 404


def test_patch_updates_fields(admin_client):
    created = _create(admin_client, name="수정전식당", memo="원래 메모").json()

    resp = admin_client.patch(
        f"{URL}/{created['id']}",
        json={
            "name": "수정후식당",
            "business_number": "999-88-77777",
            "address": "전북 전주시 덕진구 기린대로 210",
            "phone": "063-100-3003",
            "memo": "메모 수정됨",
        },
    )
    assert resp.status_code == 200, resp.text

    body = resp.json()
    assert body["id"] == created["id"]
    assert body["name"] == "수정후식당"
    assert body["business_number"] == "9998877777"
    assert body["address"] == "전북 전주시 덕진구 기린대로 210"
    assert body["phone"] == "063-100-3003"
    assert body["memo"] == "메모 수정됨"

    # 실제로 저장됐는지 재조회로 확인
    again = admin_client.get(f"{URL}/{created['id']}").json()
    assert again["name"] == "수정후식당"


def test_patch_is_partial(admin_client):
    created = _create(admin_client, name="부분수정식당", memo="유지될 메모").json()
    body = admin_client.patch(f"{URL}/{created['id']}", json={"phone": "063-100-4004"}).json()
    assert body["name"] == "부분수정식당"
    assert body["memo"] == "유지될 메모"
    assert body["phone"] == "063-100-4004"


def test_patch_to_duplicate_business_number_conflicts(admin_client):
    _create(admin_client, name="선점식당", business_number="5556667777")
    other = _create(admin_client, name="다른식당", business_number="1112223333").json()

    resp = admin_client.patch(f"{URL}/{other['id']}", json={"business_number": "555-66-67777"})
    assert resp.status_code == 409


def test_patch_preserves_balance(admin_client):
    created = _create(admin_client, name="잔액유지식당", initial_balance=88_000).json()
    body = admin_client.patch(f"{URL}/{created['id']}", json={"name": "이름만변경"}).json()
    assert body["balance"] == 88_000, "식당 수정이 원장을 건드려선 안 된다"


# ══════════════════════════════════════════════════════════════════
#  보관 (archive) — 삭제하지 않는다
# ══════════════════════════════════════════════════════════════════
def test_archived_restaurants_are_excluded_unless_requested(admin_client):
    archived = _create(admin_client, name="보관식당", initial_balance=40_000).json()
    active = _create(admin_client, name="활성식당", initial_balance=70_000).json()

    patched = admin_client.patch(f"{URL}/{archived['id']}", json={"is_archived": True})
    assert patched.status_code == 200
    assert patched.json()["is_archived"] is True

    default = admin_client.get(URL).json()
    assert [r["id"] for r in default["items"]] == [active["id"]]
    assert default["total"] == 1
    assert default["total_balance"] == 70_000, "archived 는 총 잔액에서 제외 (§2.2)"

    included = admin_client.get(URL, params={"include_archived": True}).json()
    assert {r["id"] for r in included["items"]} == {archived["id"], active["id"]}
    assert included["total"] == 2


def test_archived_restaurant_is_still_directly_readable(admin_client):
    """목록에서만 숨긴다. 이력 조회는 계속 가능해야 한다."""
    created = _create(admin_client, name="보관후조회식당", initial_balance=12_000).json()
    admin_client.patch(f"{URL}/{created['id']}", json={"is_archived": True})

    body = admin_client.get(f"{URL}/{created['id']}").json()
    assert body["is_archived"] is True
    assert body["balance"] == 12_000
    assert len(body["recent_transactions"]) == 1


def test_unarchive_restores_visibility(admin_client):
    created = _create(admin_client, name="복구식당").json()
    admin_client.patch(f"{URL}/{created['id']}", json={"is_archived": True})
    assert admin_client.get(URL).json()["items"] == []

    admin_client.patch(f"{URL}/{created['id']}", json={"is_archived": False})
    assert _names(admin_client.get(URL).json()) == ["복구식당"]


# ══════════════════════════════════════════════════════════════════
#  구성원 권한 — 식당 등록/수정은 관리자 전용이 아니다
# ══════════════════════════════════════════════════════════════════
def test_member_can_create_and_charge(member_client):
    resp = _create(member_client, name="구성원등록식당", initial_balance=30_000)
    assert resp.status_code == 201
    assert resp.json()["balance"] == 30_000
