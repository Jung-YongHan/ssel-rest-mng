"""영수증 업로드 / 확정 — CONTRACT.md §2.3.

핵심은 `confirm` 이다. 식당 생성 + CHARGE + USE 를 **한 트랜잭션**에서 처리하고,
성공하면 영수증에 `consumed_at` 을 찍어 재사용을 막는다.

OCR 은 `stub_ocr` fixture 로 항상 오프라인 스텁으로 고정한다 (네트워크 호출 0).
"""

from __future__ import annotations

URL = "/api/receipts"


def _confirm(client, receipt_id: int, **body):
    return client.post(f"{URL}/{receipt_id}/confirm", json=body)


def _new_restaurant_payload(name="신규선결제식당", business_number="6011000099"):
    return {
        "name": name,
        "business_number": business_number,
        "address": "전북 전주시 덕진구 백제대로 99",
        "phone": "063-100-9009",
        "memo": "영수증 스캔으로 등록",
    }


# ══════════════════════════════════════════════════════════════════
#  업로드
# ══════════════════════════════════════════════════════════════════
def test_upload_returns_201_with_null_parsed_when_ocr_is_off(
    member_client, stub_ocr, upload_receipt
):
    resp = upload_receipt(member_client)
    assert resp.status_code == 201, resp.text

    body = resp.json()
    assert set(body) == {"receipt", "parsed", "match", "duplicate"}

    receipt = body["receipt"]
    assert receipt["ocr_status"] in ("done", "failed"), "OCR 시도 결과가 반영돼야 한다"
    assert receipt["image_url"] == f"{URL}/{receipt['id']}/image"
    assert receipt["consumed_at"] is None
    assert receipt["uploaded_by"]["email"] == member_client.user["email"]
    assert receipt["created_at"].endswith("+00:00")

    # 읽어낸 값이 없어도 201 — 프론트가 수동 입력으로 이어간다 (§2.3)
    assert set(body["parsed"]) == {
        "store_name",
        "business_number",
        "address",
        "phone",
        "total_amount",
        "paid_at",
    }
    assert all(value is None for value in body["parsed"].values())

    assert body["match"] == {"matched_by": None, "restaurant": None, "candidates": []}
    assert body["duplicate"] is None


def test_upload_returns_201_even_when_ocr_fails(member_client, stub_ocr, upload_receipt):
    stub_ocr(error="모델 서버가 응답하지 않습니다")
    resp = upload_receipt(member_client)

    assert resp.status_code == 201, "OCR 실패해도 201 (§2.3)"
    body = resp.json()
    assert body["receipt"]["ocr_status"] == "failed"
    assert body["receipt"]["ocr_error"]
    assert all(value is None for value in body["parsed"].values())


def test_upload_stores_parsed_values(member_client, stub_ocr, upload_receipt):
    stub_ocr(
        {
            "store_name": "행복분식",
            "business_number": "6011000011",
            "address": "전북 전주시 덕진구 백제대로 123",
            "phone": "063-100-1001",
            "total_amount": 42_000,
            "paid_at": "2026-07-15T12:30:00",
        },
        raw='{"store_name": "행복분식"}',
    )
    body = upload_receipt(member_client).json()

    assert body["receipt"]["ocr_status"] == "done"
    assert body["receipt"]["ocr_error"] is None
    assert body["parsed"]["store_name"] == "행복분식"
    assert body["parsed"]["business_number"] == "6011000011"
    assert body["parsed"]["total_amount"] == 42_000
    assert body["parsed"]["paid_at"] is not None


def test_upload_matches_existing_restaurant_by_business_number(
    member_client, stub_ocr, upload_receipt, make_restaurant, make_tx
):
    target = make_restaurant("매칭식당", business_number="6011000055")
    make_tx(target, "CHARGE", 100_000)

    stub_ocr({"store_name": "매칭식당", "business_number": "6011000055", "total_amount": 23_000})
    body = upload_receipt(member_client).json()

    assert body["match"]["matched_by"] == "business_number"
    assert body["match"]["restaurant"]["id"] == target.id
    assert body["match"]["restaurant"]["balance"] == 100_000
    assert body["match"]["candidates"][0]["score"] == 100
    assert body["match"]["candidates"][0]["reason"] == "business_number"


def test_upload_requires_auth(client, jpeg_bytes):
    resp = client.post(URL, files={"file": ("r.jpg", jpeg_bytes(), "image/jpeg")})
    assert resp.status_code == 401


def test_upload_rejects_non_image(member_client, stub_ocr):
    resp = member_client.post(
        URL, files={"file": ("notes.txt", b"just some text", "text/plain")}
    )
    assert resp.status_code in (400, 415, 422), resp.text
    assert resp.status_code != 201


def test_get_receipt_does_not_rerun_ocr(member_client, stub_ocr, upload_receipt):
    stub_ocr({"store_name": "재조회식당", "total_amount": 11_000})
    uploaded = upload_receipt(member_client).json()
    receipt_id = uploaded["receipt"]["id"]

    # OCR 결과를 바꿔치기해도, 재조회는 저장된 값을 그대로 돌려줘야 한다
    stub_ocr({"store_name": "바뀐값이보이면버그"})
    again = member_client.get(f"{URL}/{receipt_id}")

    assert again.status_code == 200
    assert again.json()["parsed"]["store_name"] == "재조회식당"


def test_get_unknown_receipt_is_404(member_client):
    assert member_client.get(f"{URL}/999999").status_code == 404


# ══════════════════════════════════════════════════════════════════
#  이미지 조회 — 인증 필요
# ══════════════════════════════════════════════════════════════════
def test_receipt_image_requires_auth(client, member_client, stub_ocr, upload_receipt):
    receipt_id = upload_receipt(member_client).json()["receipt"]["id"]

    anonymous = client.get(f"{URL}/{receipt_id}/image")
    assert anonymous.status_code == 401, "영수증에는 결제정보가 있다 — 무인증 노출 금지"

    authenticated = member_client.get(f"{URL}/{receipt_id}/image")
    assert authenticated.status_code == 200
    assert authenticated.headers["content-type"].startswith("image/")
    assert len(authenticated.content) > 0


# ══════════════════════════════════════════════════════════════════
#  confirm — UC1: 신규 식당 등록 + 선결제 + 즉시 사용
# ══════════════════════════════════════════════════════════════════
def test_confirm_register_and_charge_with_immediate_use(
    member_client, stub_ocr, upload_receipt
):
    receipt_id = upload_receipt(member_client).json()["receipt"]["id"]

    resp = _confirm(
        member_client,
        receipt_id,
        action="register_and_charge",
        restaurant=_new_restaurant_payload(),
        charge_amount=300_000,
        use_amount=42_000,
        memo="첫 선결제",
        parsed={
            "store_name": "신규선결제식당",
            "business_number": "6011000099",
            "address": "전북 전주시 덕진구 백제대로 99",
            "phone": None,
            "total_amount": 42_000,
            "paid_at": "2026-07-01T12:30:00",
        },
    )
    assert resp.status_code == 200, resp.text

    body = resp.json()
    assert set(body) == {
        "restaurant",
        "transactions",
        "balance_before",
        "balance_after",
        "warnings",
    }
    assert body["balance_before"] == 0
    assert body["balance_after"] == 258_000

    restaurant = body["restaurant"]
    assert restaurant["name"] == "신규선결제식당"
    assert restaurant["business_number"] == "6011000099"
    assert restaurant["balance"] == 258_000
    assert restaurant["charge_total"] == 300_000
    assert restaurant["use_total"] == 42_000

    txs = body["transactions"]
    assert [t["type"] for t in txs] == ["CHARGE", "USE"], "CHARGE, USE 순 (§2.3)"
    assert [t["amount"] for t in txs] == [300_000, 42_000]
    assert all(t["receipt_id"] == receipt_id for t in txs), "생성된 거래에 영수증이 연결된다"
    assert all(t["has_receipt"] is True for t in txs)
    assert all(t["restaurant_id"] == restaurant["id"] for t in txs)

    # consumed_at 이 찍혀야 한다
    reread = member_client.get(f"{URL}/{receipt_id}").json()
    assert reread["receipt"]["consumed_at"] is not None
    # 화면에서 고친 parsed 값도 반영 저장된다
    assert reread["parsed"]["store_name"] == "신규선결제식당"


def test_confirm_register_and_charge_without_use(member_client, stub_ocr, upload_receipt):
    receipt_id = upload_receipt(member_client).json()["receipt"]["id"]

    body = _confirm(
        member_client,
        receipt_id,
        action="register_and_charge",
        restaurant=_new_restaurant_payload("사용없음식당", "6011000098"),
        charge_amount=150_000,
    ).json()

    assert [t["type"] for t in body["transactions"]] == ["CHARGE"]
    assert body["balance_after"] == 150_000


def test_confirm_use_amount_zero_creates_no_use(member_client, stub_ocr, upload_receipt):
    receipt_id = upload_receipt(member_client).json()["receipt"]["id"]
    body = _confirm(
        member_client,
        receipt_id,
        action="register_and_charge",
        restaurant=_new_restaurant_payload("영원사용식당", "6011000097"),
        charge_amount=100_000,
        use_amount=0,
    ).json()
    assert [t["type"] for t in body["transactions"]] == ["CHARGE"], "use_amount=0 → USE 없음"


def test_second_confirm_on_same_receipt_conflicts(member_client, stub_ocr, upload_receipt):
    receipt_id = upload_receipt(member_client).json()["receipt"]["id"]
    payload = {
        "action": "register_and_charge",
        "restaurant": _new_restaurant_payload("한번만식당", "6011000096"),
        "charge_amount": 100_000,
    }

    first = _confirm(member_client, receipt_id, **payload)
    assert first.status_code == 200, first.text

    second = _confirm(
        member_client,
        receipt_id,
        action="charge",
        restaurant_id=first.json()["restaurant"]["id"],
        charge_amount=50_000,
    )
    assert second.status_code == 409, "consumed 된 영수증 재사용 차단 (§2.3)"
    assert "이미 처리된 영수증" in second.json()["detail"]


def test_confirm_register_with_existing_business_number_conflicts(
    member_client, stub_ocr, upload_receipt, make_restaurant
):
    make_restaurant("이미있는식당", business_number="6011000095")
    receipt_id = upload_receipt(member_client).json()["receipt"]["id"]

    resp = _confirm(
        member_client,
        receipt_id,
        action="register_and_charge",
        restaurant=_new_restaurant_payload("중복등록시도식당", "601-10-00095"),
        charge_amount=100_000,
    )
    assert resp.status_code == 409
    assert "이미있는식당" in resp.json()["detail"]

    # 실패했으므로 영수증은 아직 재사용 가능해야 한다 (롤백 확인)
    assert member_client.get(f"{URL}/{receipt_id}").json()["receipt"]["consumed_at"] is None


# ══════════════════════════════════════════════════════════════════
#  confirm — UC2: 기존 식당 잔액 사용
# ══════════════════════════════════════════════════════════════════
def test_confirm_use_on_existing_restaurant(
    member_client, stub_ocr, upload_receipt, make_restaurant, make_tx
):
    target = make_restaurant("기존선결제식당", business_number="6011000077")
    make_tx(target, "CHARGE", 200_000)

    receipt_id = upload_receipt(member_client).json()["receipt"]["id"]
    resp = _confirm(
        member_client,
        receipt_id,
        action="use",
        restaurant_id=target.id,
        use_amount=35_000,
        memo="점심 3인",
    )
    assert resp.status_code == 200, resp.text

    body = resp.json()
    assert body["balance_before"] == 200_000
    assert body["balance_after"] == 165_000
    assert [t["type"] for t in body["transactions"]] == ["USE"]
    assert body["transactions"][0]["amount"] == 35_000
    assert body["transactions"][0]["memo"] == "점심 3인"
    assert body["transactions"][0]["receipt_id"] == receipt_id
    assert body["restaurant"]["balance"] == 165_000


def test_confirm_use_over_balance_conflicts_then_allows_negative(
    member_client, stub_ocr, upload_receipt, make_restaurant, make_tx
):
    target = make_restaurant("잔액부족식당", business_number="6011000088")
    make_tx(target, "CHARGE", 30_000)

    receipt_id = upload_receipt(member_client).json()["receipt"]["id"]
    payload = {"action": "use", "restaurant_id": target.id, "use_amount": 50_000}

    blocked = _confirm(member_client, receipt_id, **payload)
    assert blocked.status_code == 409
    assert "잔액이 부족" in blocked.json()["detail"]

    # 롤백됐으므로 잔액도 그대로, 영수증도 아직 미사용
    assert member_client.get(f"{URL}/{receipt_id}").json()["receipt"]["consumed_at"] is None

    allowed = _confirm(member_client, receipt_id, **payload, allow_negative=True)
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["balance_after"] == -20_000
    assert allowed.json()["warnings"], "음수 잔액 경고가 있어야 한다"
    assert member_client.get(f"{URL}/{receipt_id}").json()["receipt"]["consumed_at"] is not None


# ══════════════════════════════════════════════════════════════════
#  confirm — UC3: 기존 식당 추가 선결제
# ══════════════════════════════════════════════════════════════════
def test_confirm_charge_on_existing_restaurant(
    member_client, stub_ocr, upload_receipt, make_restaurant, make_tx
):
    target = make_restaurant("추가충전식당", business_number="6011000066")
    make_tx(target, "CHARGE", 50_000)
    make_tx(target, "USE", 30_000)

    receipt_id = upload_receipt(member_client).json()["receipt"]["id"]
    resp = _confirm(
        member_client,
        receipt_id,
        action="charge",
        restaurant_id=target.id,
        charge_amount=200_000,
        memo="잔액 부족해서 추가 선결제",
    )
    assert resp.status_code == 200, resp.text

    body = resp.json()
    assert body["balance_before"] == 20_000
    assert body["balance_after"] == 220_000
    assert [t["type"] for t in body["transactions"]] == ["CHARGE"]


def test_confirm_charge_with_immediate_use(
    member_client, stub_ocr, upload_receipt, make_restaurant, make_tx
):
    target = make_restaurant("충전후사용식당", business_number="6011000065")
    make_tx(target, "CHARGE", 10_000)

    receipt_id = upload_receipt(member_client).json()["receipt"]["id"]
    body = _confirm(
        member_client,
        receipt_id,
        action="charge",
        restaurant_id=target.id,
        charge_amount=100_000,
        use_amount=25_000,
    ).json()

    assert [t["type"] for t in body["transactions"]] == ["CHARGE", "USE"]
    assert body["balance_after"] == 85_000


# ══════════════════════════════════════════════════════════════════
#  confirm — 입력 검증
# ══════════════════════════════════════════════════════════════════
def test_confirm_requires_restaurant_id_for_charge_and_use(
    member_client, stub_ocr, upload_receipt
):
    receipt_id = upload_receipt(member_client).json()["receipt"]["id"]
    for action in ("charge", "use"):
        resp = _confirm(member_client, receipt_id, action=action, charge_amount=1_000)
        assert resp.status_code in (400, 422), f"{action}: restaurant_id 필수 (§2.3)"


def test_confirm_requires_restaurant_body_for_register(member_client, stub_ocr, upload_receipt):
    receipt_id = upload_receipt(member_client).json()["receipt"]["id"]
    resp = _confirm(
        member_client, receipt_id, action="register_and_charge", charge_amount=100_000
    )
    assert resp.status_code in (400, 422)


def test_confirm_requires_positive_charge_amount(
    member_client, stub_ocr, upload_receipt, make_restaurant
):
    target = make_restaurant("금액검증식당")
    receipt_id = upload_receipt(member_client).json()["receipt"]["id"]

    for amount in (0, -1_000):
        resp = _confirm(
            member_client,
            receipt_id,
            action="charge",
            restaurant_id=target.id,
            charge_amount=amount,
        )
        assert resp.status_code in (400, 422), f"charge_amount={amount}"


def test_confirm_rejects_unknown_action(member_client, stub_ocr, upload_receipt):
    receipt_id = upload_receipt(member_client).json()["receipt"]["id"]
    resp = _confirm(member_client, receipt_id, action="플러팅", charge_amount=1_000)
    assert resp.status_code == 422


def test_confirm_on_unknown_receipt_is_404(member_client, make_restaurant):
    target = make_restaurant("없는영수증식당")
    resp = _confirm(
        member_client, 999_999, action="charge", restaurant_id=target.id, charge_amount=1_000
    )
    assert resp.status_code == 404


def test_confirm_requires_auth(client, member_client, stub_ocr, upload_receipt):
    receipt_id = upload_receipt(member_client).json()["receipt"]["id"]
    resp = _confirm(client, receipt_id, action="charge", restaurant_id=1, charge_amount=1_000)
    assert resp.status_code == 401


# ══════════════════════════════════════════════════════════════════
#  reocr
# ══════════════════════════════════════════════════════════════════
def test_reocr_replaces_parsed_values(member_client, stub_ocr, upload_receipt):
    stub_ocr(error="일시적 실패")
    receipt_id = upload_receipt(member_client).json()["receipt"]["id"]

    stub_ocr({"store_name": "재시도성공식당", "total_amount": 17_000})
    resp = member_client.post(f"{URL}/{receipt_id}/reocr")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["receipt"]["ocr_status"] == "done"
    assert body["parsed"]["store_name"] == "재시도성공식당"
    assert body["parsed"]["total_amount"] == 17_000
