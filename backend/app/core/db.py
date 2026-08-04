"""SQLAlchemy 엔진 / 세션 / Base."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    pass


def _engine_kwargs() -> dict:
    if settings.is_sqlite:
        # SQLite 파일은 미리 디렉터리가 있어야 한다
        settings.ensure_dirs()
        return {"connect_args": {"check_same_thread": False}}
    return {"pool_pre_ping": True}


engine = create_engine(settings.sqlalchemy_url, future=True, **_engine_kwargs())

SessionLocal = sessionmaker(
    bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, class_=Session
)


if settings.is_sqlite:

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - 커넥션 훅
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")  # FK 제약 실제 적용
        cur.execute("PRAGMA journal_mode=WAL")  # 동시 읽기 개선
        cur.execute("PRAGMA busy_timeout=5000")
        cur.close()


def get_db() -> Iterator[Session]:
    """FastAPI 의존성: 요청당 세션 하나."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
