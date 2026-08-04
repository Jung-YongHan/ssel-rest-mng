"""시간 처리 규약.

- DB 에는 **naive UTC** 로 저장한다 (SQLite/PG 어디서나 일관됨).
- 클라이언트로 내보낼 때는 `+00:00` 을 붙여 aware ISO 문자열로 직렬화한다
  (브라우저가 자동으로 KST 로 표시).
- 클라이언트에서 들어온 naive datetime 은 **KST 벽시계**로 간주해 UTC 로 변환한다
  (사용자가 `<input type="datetime-local">` 로 입력한 값이기 때문).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

KST = timezone(timedelta(hours=9), name="KST")
UTC = timezone.utc


def utc_now() -> datetime:
    """현재 시각 (naive UTC) — DB 저장용."""
    return datetime.now(UTC).replace(tzinfo=None)


def to_utc_naive(dt: datetime) -> datetime:
    """어떤 datetime 이든 naive UTC 로 정규화.

    naive 입력은 KST 벽시계로 간주한다.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=KST)
    return dt.astimezone(UTC).replace(tzinfo=None)


def as_utc_aware(dt: datetime | None) -> datetime | None:
    """DB 의 naive UTC → aware UTC (직렬화용)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def to_kst(dt: datetime | None) -> datetime | None:
    """DB 의 naive UTC → aware KST (서버측 표시/집계용)."""
    aware = as_utc_aware(dt)
    return aware.astimezone(KST) if aware else None


def kst_today() -> date:
    return datetime.now(KST).date()


def kst_day_bounds(day: date) -> tuple[datetime, datetime]:
    """KST 하루의 [시작, 끝) 을 naive UTC 범위로."""
    start = datetime(day.year, day.month, day.day, tzinfo=KST)
    end = start + timedelta(days=1)
    return start.astimezone(UTC).replace(tzinfo=None), end.astimezone(UTC).replace(tzinfo=None)


def kst_month_bounds(year: int, month: int) -> tuple[datetime, datetime]:
    """KST 한 달의 [시작, 끝) 을 naive UTC 범위로."""
    start = datetime(year, month, 1, tzinfo=KST)
    end = datetime(year + (month == 12), (month % 12) + 1, 1, tzinfo=KST)
    return start.astimezone(UTC).replace(tzinfo=None), end.astimezone(UTC).replace(tzinfo=None)


def kst_month_key(dt: datetime) -> str:
    """naive UTC → 'YYYY-MM' (KST 기준)."""
    k = to_kst(dt)
    return f"{k.year:04d}-{k.month:02d}"
