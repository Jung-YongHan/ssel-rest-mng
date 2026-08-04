"""영수증 → 식당 매칭 — CONTRACT.md §4.

    1) 사업자등록번호 정확일치  → matched_by="business_number", score=100
    2) rapidfuzz 상호명 유사도  → 최고점 >= 88 이면 matched_by="name"
       그 외에는 score >= 60 인 것만 candidates 로 (matched_by=None)

여기는 순수 로직이라 HTTP 를 거치지 않고 서비스를 직접 호출한다.
"""

from __future__ import annotations

import pytest

from app.services import matching

# 계약에 명시된 임계값 (구현 상수가 아니라 계약 숫자를 그대로 쓴다)
AUTO_THRESHOLD = 88
CANDIDATE_MIN = 60


def _parsed(store_name: str | None = None, business_number: str | None = None) -> dict:
    """ParsedReceipt 호환 dict."""
    return {"store_name": store_name, "business_number": business_number}


def _ids(candidates) -> list[int]:
    return [c.restaurant.id for c in candidates]


# ══════════════════════════════════════════════════════════════════
#  normalize_business_number
# ══════════════════════════════════════════════════════════════════
def test_normalize_business_number_with_hyphens():
    assert matching.normalize_business_number("123-45-67890") == "1234567890"


def test_normalize_business_number_already_normalized():
    assert matching.normalize_business_number("1234567890") == "1234567890"


@pytest.mark.parametrize(
    "raw",
    [
        " 123 45 67890 ",
        "123.45.67890",
        "사업자등록번호: 123-45-67890",
        "123-45-67890 ",
    ],
)
def test_normalize_business_number_strips_any_non_digit(raw):
    assert matching.normalize_business_number(raw) == "1234567890"


@pytest.mark.parametrize(
    "junk",
    [
        None,
        "",
        "   ",
        "사업자번호 없음",
        "없음",
        "-",
        "abc-de-fghij",
    ],
)
def test_normalize_business_number_rejects_junk(junk):
    assert matching.normalize_business_number(junk) is None


@pytest.mark.parametrize(
    "wrong_length",
    [
        "123456789",  # 9자리
        "12345678901",  # 11자리
        "123-45-6789",  # 9자리
        "1",
        "12345678901234",
    ],
)
def test_normalize_business_number_rejects_wrong_length(wrong_length):
    assert matching.normalize_business_number(wrong_length) is None, (
        "10자리가 아니면 None (§4)"
    )


# ══════════════════════════════════════════════════════════════════
#  format_business_number
# ══════════════════════════════════════════════════════════════════
def test_format_business_number():
    assert matching.format_business_number("1234567890") == "123-45-67890"
    assert matching.format_business_number("123-45-67890") == "123-45-67890"
    assert matching.format_business_number(None) is None
    assert matching.format_business_number("") is None


def test_normalize_and_format_round_trip():
    normalized = matching.normalize_business_number("601-10-00011")
    assert normalized == "6011000011"
    assert matching.format_business_number(normalized) == "601-10-00011"


# ══════════════════════════════════════════════════════════════════
#  normalize_name
# ══════════════════════════════════════════════════════════════════
@pytest.mark.parametrize(
    "variant",
    [
        "행복분식",
        "행복 분식",
        "  행복분식  ",
        "행복분식 (전북대점)",
        "행복분식 본점",
        "행복-분식",
    ],
)
def test_normalize_name_collapses_variants(variant):
    """공백·괄호·지점표기·기호를 제거해 같은 이름으로 모은다 (§4)."""
    assert matching.normalize_name(variant) == matching.normalize_name("행복분식")


def test_normalize_name_is_case_folded():
    assert matching.normalize_name("Happy BUNSIK") == matching.normalize_name("happy bunsik")


def test_normalize_name_handles_empty():
    assert matching.normalize_name("") == ""


def test_normalize_name_keeps_distinct_names_distinct():
    assert matching.normalize_name("행복분식") != matching.normalize_name("청춘국수")


# ══════════════════════════════════════════════════════════════════
#  match_restaurant
# ══════════════════════════════════════════════════════════════════
def test_business_number_match_wins_over_better_name_score(db, make_restaurant):
    """이름이 100% 같은 식당이 있어도 사업자번호 일치가 이긴다 (§4 우선순위)."""
    name_twin = make_restaurant("행복분식", business_number="1111111111")
    bn_target = make_restaurant("전혀다른이름국수", business_number="2222222222")

    outcome = matching.match_restaurant(db, _parsed("행복분식", "222-22-22222"))

    assert outcome.matched_by == "business_number"
    assert outcome.restaurant is not None
    assert outcome.restaurant.id == bn_target.id

    top = outcome.candidates[0]
    assert top.restaurant.id == bn_target.id
    assert top.score == 100
    assert top.reason == "business_number"
    # 이름이 같은 쪽은 후보로만 남는다
    assert name_twin.id in _ids(outcome.candidates)


def test_near_identical_name_auto_matches(db, make_restaurant):
    target = make_restaurant("든든한식당", business_number="3333333333")
    make_restaurant("완전히다른곳", business_number="4444444444")

    outcome = matching.match_restaurant(db, _parsed("든든한 식당"))

    assert outcome.matched_by == "name"
    assert outcome.restaurant is not None
    assert outcome.restaurant.id == target.id
    assert outcome.candidates[0].score >= AUTO_THRESHOLD
    assert outcome.candidates[0].reason == "name"


def test_branch_suffix_still_matches(db, make_restaurant):
    target = make_restaurant("청춘국수")
    outcome = matching.match_restaurant(db, _parsed("청춘국수 전북대점"))
    assert outcome.matched_by == "name"
    assert outcome.restaurant.id == target.id


def test_unrelated_names_do_not_match(db, make_restaurant):
    make_restaurant("행복분식")
    make_restaurant("청춘국수")

    outcome = matching.match_restaurant(db, _parsed("무관한커피전문점"))

    assert outcome.matched_by is None
    assert outcome.restaurant is None
    # 후보로 나타날 수는 있으나 자동확정 임계값을 넘어선 안 된다
    for candidate in outcome.candidates:
        assert candidate.score < AUTO_THRESHOLD
        assert candidate.score >= CANDIDATE_MIN


def test_candidate_scores_respect_contract_thresholds(db, make_restaurant):
    """자동확정이 되든 후보로만 남든, 60/88 규약은 항상 지켜져야 한다."""
    make_restaurant("행복분식")
    make_restaurant("행복반점")
    make_restaurant("청춘국수")

    outcome = matching.match_restaurant(db, _parsed("행복분식"))

    for candidate in outcome.candidates:
        assert candidate.score >= CANDIDATE_MIN, "60점 미만은 후보에도 넣지 않는다"
    if outcome.matched_by == "name":
        assert outcome.candidates[0].score >= AUTO_THRESHOLD
        assert outcome.restaurant is not None
    else:
        assert outcome.restaurant is None
        assert all(c.score < AUTO_THRESHOLD for c in outcome.candidates)


def test_candidates_are_sorted_desc_and_limited(db, make_restaurant):
    for i in range(8):
        make_restaurant(f"행복분식{i}")

    outcome = matching.match_restaurant(db, _parsed("행복분식"), limit=3)

    assert len(outcome.candidates) <= 3
    scores = [c.score for c in outcome.candidates]
    assert scores == sorted(scores, reverse=True)


def test_default_limit_is_five(db, make_restaurant):
    for i in range(9):
        make_restaurant(f"든든한식당{i}")
    outcome = matching.match_restaurant(db, _parsed("든든한식당"))
    assert len(outcome.candidates) <= 5, "candidates 는 최대 5개 (§2.3)"


def test_no_parsed_values_yields_empty_outcome(db, make_restaurant):
    make_restaurant("행복분식")
    outcome = matching.match_restaurant(db, _parsed(None, None))
    assert outcome.matched_by is None
    assert outcome.restaurant is None
    assert outcome.candidates == []


def test_unknown_business_number_falls_back_to_name(db, make_restaurant):
    target = make_restaurant("행복분식", business_number="1111111111")
    # 영수증의 사업자번호는 등록되지 않은 번호 → 이름으로 폴백
    outcome = matching.match_restaurant(db, _parsed("행복분식", "999-99-99999"))
    assert outcome.matched_by == "name"
    assert outcome.restaurant.id == target.id


def test_malformed_business_number_is_ignored(db, make_restaurant):
    """10자리가 아닌 값은 아예 없는 것으로 취급한다."""
    target = make_restaurant("행복분식", business_number="1111111111")
    outcome = matching.match_restaurant(db, _parsed("행복분식", "123"))
    assert outcome.matched_by == "name"
    assert outcome.restaurant.id == target.id


def test_match_accepts_attribute_style_parsed(db, make_restaurant):
    """dict 뿐 아니라 pydantic 모델 같은 속성 접근 객체도 받아야 한다."""
    from types import SimpleNamespace

    target = make_restaurant("든든한식당", business_number="3333333333")
    parsed = SimpleNamespace(store_name="든든한식당", business_number="333-33-33333")

    outcome = matching.match_restaurant(db, parsed)
    assert outcome.matched_by == "business_number"
    assert outcome.restaurant.id == target.id
