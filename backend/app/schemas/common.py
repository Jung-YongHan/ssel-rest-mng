"""스키마 공용 타입 — 모든 라우터 스키마가 여기 것을 재사용한다."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from dateutil import parser as date_parser
from pydantic import BaseModel, BeforeValidator, ConfigDict, PlainSerializer

from app.core.timeutil import as_utc_aware, to_utc_naive

# ── datetime 규약 ────────────────────────────────────────────────
# 응답: DB 의 naive UTC → '...+00:00' aware ISO (브라우저가 KST 로 표시)
UtcOut = Annotated[
    datetime,
    PlainSerializer(lambda d: as_utc_aware(d).isoformat(), return_type=str, when_used="json"),
]


def _to_utc_naive_input(v: Any) -> Any:
    """요청 datetime 정규화: aware → UTC, naive → KST 벽시계로 해석 → naive UTC.

    ⚠️ 문자열도 **반드시 여기서** 파싱해야 한다. JSON 은 datetime 을 문자열로 보내므로
    `isinstance(v, datetime)` 만 검사하면 `"2026-08-04T12:30"` 이 그대로 통과해
    Pydantic 이 naive datetime 으로 파싱하고, 우리 규약상 그것은 UTC 로 취급되어
    **모든 시각이 9시간 틀어진다.** (`<input type="datetime-local">` 이 보내는 형식)
    """
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        try:
            v = date_parser.parse(s)
        except (ValueError, OverflowError):
            raise ValueError("날짜/시간 형식이 올바르지 않습니다.") from None
    if isinstance(v, datetime):
        return to_utc_naive(v)
    return v


# 요청용 datetime — 스키마에서는 이 타입만 쓸 것 (raw `datetime` 금지)
KstIn = Annotated[datetime, BeforeValidator(_to_utc_naive_input)]


class ApiModel(BaseModel):
    """ORM 객체에서 바로 직렬화 가능한 응답 모델 베이스."""

    model_config = ConfigDict(from_attributes=True)


class UserBrief(ApiModel):
    """기록의 '누가' — 이력 추적 표시용 최소 정보."""

    id: int
    name: str
    email: str


class MessageOut(BaseModel):
    message: str


class Page(ApiModel):
    total: int
    limit: int
    offset: int
