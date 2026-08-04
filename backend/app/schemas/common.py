"""스키마 공용 타입 — 모든 라우터 스키마가 여기 것을 재사용한다."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, PlainSerializer

from app.core.timeutil import as_utc_aware, to_utc_naive

# ── datetime 규약 ────────────────────────────────────────────────
# 응답: DB 의 naive UTC → '...+00:00' aware ISO (브라우저가 KST 로 표시)
UtcOut = Annotated[
    datetime,
    PlainSerializer(lambda d: as_utc_aware(d).isoformat(), return_type=str, when_used="json"),
]

# 요청: aware 면 그대로 UTC 변환, naive 면 KST 벽시계로 간주 → naive UTC
KstIn = Annotated[datetime, BeforeValidator(lambda v: to_utc_naive(v) if isinstance(v, datetime) else v)]


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
