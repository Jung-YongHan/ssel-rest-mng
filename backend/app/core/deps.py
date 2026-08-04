"""FastAPI 공용 의존성: DB 세션, 현재 사용자, 관리자 권한."""

from __future__ import annotations

from typing import Annotated

from fastapi import Cookie, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.security import decode_access_token
from app.models import User

DbSession = Annotated[Session, Depends(get_db)]

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED, detail="로그인이 필요합니다."
)


def _extract_token(cookie_token: str | None, authorization: str | None) -> str | None:
    """1순위 httpOnly 쿠키, 2순위 Authorization: Bearer (API 테스트/스크립트용)."""
    if cookie_token:
        return cookie_token
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


def get_current_user(
    db: DbSession,
    ssel_token: Annotated[str | None, Cookie(alias=settings.cookie_name)] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    token = _extract_token(ssel_token, authorization)
    if not token:
        raise _UNAUTHORIZED

    payload = decode_access_token(token)
    if not payload or not payload.get("sub"):
        raise _UNAUTHORIZED

    try:
        user_id = int(payload["sub"])
    except (TypeError, ValueError):
        raise _UNAUTHORIZED from None

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="계정을 사용할 수 없습니다."
        )
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_admin(user: CurrentUser) -> User:
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="관리자 권한이 필요합니다."
        )
    return user


AdminUser = Annotated[User, Depends(require_admin)]
