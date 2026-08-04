"""영수증 → 식당 매칭 — CONTRACT.md §4.

우선순위
  1) 사업자등록번호 정확일치 (가장 신뢰도 높음) → score=100
  2) rapidfuzz WRatio 상호명 유사도. 최고점 >= 88 이면 자동확정,
     그 외에는 60점 이상만 후보로 보여주고 사용자가 고르게 한다.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Literal, Mapping

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Restaurant

# 자동확정 임계값 / 후보 노출 최소 점수
NAME_AUTO_THRESHOLD = 88
NAME_MIN_SCORE = 60

MatchReason = Literal["business_number", "name"]

_DIGITS_RE = re.compile(r"\D+")
_PAREN_RE = re.compile(r"[(（\[{][^)）\]}]*[)）\]}]")
_NON_WORD_RE = re.compile(r"[^0-9a-z가-힣ㄱ-ㅎㅏ-ㅣ]+")
# "○○점 / ○○지점 / ○○본점" 처럼 지점 표기는 매칭 시 무시한다
_BRANCH_SUFFIXES = ("본점", "지점", "점")
# 법인 표기 제거 ("(주)" 는 괄호 제거로 이미 사라진다)
_COMPANY_WORDS = ("주식회사", "유한회사", "합자회사")


def normalize_business_number(v: str | None) -> str | None:
    """숫자만 남기고 10자리가 아니면 None (저장·비교 모두 이 형태로 통일)."""
    if not v:
        return None
    digits = _DIGITS_RE.sub("", str(v))
    return digits if len(digits) == 10 else None


def format_business_number(v: str | None) -> str | None:
    """표시용 하이픈 포맷: 1234567890 → 123-45-67890."""
    if not v:
        return None
    digits = _DIGITS_RE.sub("", str(v))
    if len(digits) != 10:
        return v or None
    return f"{digits[:3]}-{digits[3:5]}-{digits[5:]}"


def normalize_name(v: str) -> str:
    """상호명 정규화: 괄호 내용·공백·기호·지점표기 제거 + 소문자화."""
    if not v:
        return ""
    s = unicodedata.normalize("NFKC", str(v))
    s = _PAREN_RE.sub(" ", s)
    s = s.casefold()
    s = _NON_WORD_RE.sub("", s)
    for word in _COMPANY_WORDS:
        s = s.replace(word, "")
    for suffix in _BRANCH_SUFFIXES:
        # 지점 표기를 떼고도 최소 2글자는 남아야 한다 ("본점"만 남는 이름 방지)
        if s.endswith(suffix) and len(s) - len(suffix) >= 2:
            s = s[: -len(suffix)]
            break
    return s


@dataclass(slots=True)
class ScoredRestaurant:
    restaurant: Restaurant
    score: int
    reason: MatchReason


@dataclass(slots=True)
class MatchOutcome:
    matched_by: MatchReason | None = None
    restaurant: Restaurant | None = None
    candidates: list[ScoredRestaurant] = field(default_factory=list)


def _field(parsed: Any, key: str) -> Any:
    """dict / pydantic 모델 / ORM 객체 모두 받아들인다."""
    if parsed is None:
        return None
    if isinstance(parsed, Mapping):
        return parsed.get(key)
    return getattr(parsed, key, None)


def match_restaurant(db: Session, parsed: Any, limit: int = 5) -> MatchOutcome:
    """`parsed`(ParsedReceipt 호환) 로 식당을 찾는다."""
    bn = normalize_business_number(_field(parsed, "business_number"))
    store_name = _field(parsed, "store_name") or ""

    exact: Restaurant | None = None
    if bn:
        exact = (
            db.execute(select(Restaurant).where(Restaurant.business_number == bn))
            .scalars()
            .first()
        )

    scored: list[ScoredRestaurant] = []
    target = normalize_name(store_name)
    if target:
        rows = (
            db.execute(select(Restaurant).where(Restaurant.is_archived.is_(False)))
            .scalars()
            .all()
        )
        for r in rows:
            if exact is not None and r.id == exact.id:
                continue  # 사업자번호 일치 건은 아래에서 100점으로 따로 넣는다
            candidate = normalize_name(r.name)
            if not candidate:
                continue
            score = int(round(fuzz.WRatio(target, candidate)))
            if score >= NAME_MIN_SCORE:
                scored.append(ScoredRestaurant(restaurant=r, score=score, reason="name"))
        scored.sort(key=lambda c: (-c.score, c.restaurant.name))

    if exact is not None:
        candidates = [ScoredRestaurant(exact, 100, "business_number"), *scored]
        return MatchOutcome("business_number", exact, candidates[:limit])

    if scored and scored[0].score >= NAME_AUTO_THRESHOLD:
        return MatchOutcome("name", scored[0].restaurant, scored[:limit])

    return MatchOutcome(None, None, scored[:limit])


__all__ = [
    "MatchOutcome",
    "MatchReason",
    "NAME_AUTO_THRESHOLD",
    "NAME_MIN_SCORE",
    "ScoredRestaurant",
    "format_business_number",
    "match_restaurant",
    "normalize_business_number",
    "normalize_name",
]
