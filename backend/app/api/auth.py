"""인증 라우터 — CONTRACT.md §2.1.

토큰은 httpOnly 쿠키(`settings.cookie_name`)로 내려준다. 프론트는 `withCredentials: true`.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import func, select

from app.core.config import settings
from app.core.deps import CurrentUser, DbSession
from app.core.security import create_access_token, hash_password, verify_password
from app.models import User, UserRole
from app.schemas.auth import LoginIn, RegisterIn, UserOut
from app.schemas.common import MessageOut

router = APIRouter()

MIN_PASSWORD_LENGTH = 8


def _check_password_length(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"비밀번호는 {MIN_PASSWORD_LENGTH}자 이상이어야 합니다.",
        )


def _set_auth_cookie(response: Response, user: User) -> None:
    response.set_cookie(
        key=settings.cookie_name,
        value=create_access_token(user.id),
        httponly=True,
        samesite=settings.cookie_samesite,
        secure=settings.cookie_secure,
        max_age=settings.jwt_expire_minutes * 60,
        path="/",
    )


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterIn, response: Response, db: DbSession) -> User:
    if payload.invite_code.strip() != settings.invite_code:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="초대코드가 올바르지 않습니다."
        )
    _check_password_length(payload.password)

    exists = db.execute(select(User.id).where(User.email == payload.email)).scalar()
    if exists:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="이미 등록된 이메일입니다."
        )

    # 연구실 초기 세팅 편의: 첫 번째 가입자는 자동으로 관리자
    user_count = int(db.execute(select(func.count(User.id))).scalar() or 0)
    user = User(
        email=payload.email,
        name=payload.name,
        password_hash=hash_password(payload.password),
        role=UserRole.admin if user_count == 0 else UserRole.member,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    _set_auth_cookie(response, user)
    return user


@router.post("/login", response_model=UserOut)
def login(payload: LoginIn, response: Response, db: DbSession) -> User:
    user = db.execute(select(User).where(User.email == payload.email)).scalars().first()
    if user is None or not verify_password(payload.password, user.password_hash):
        # 계정 존재 여부를 흘리지 않도록 메시지를 하나로 통일한다
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="이메일 또는 비밀번호가 올바르지 않습니다.",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="계정을 사용할 수 없습니다."
        )

    _set_auth_cookie(response, user)
    return user


@router.post("/logout", response_model=MessageOut)
def logout(response: Response) -> dict[str, str]:
    response.delete_cookie(
        key=settings.cookie_name,
        path="/",
        samesite=settings.cookie_samesite,
        secure=settings.cookie_secure,
        httponly=True,
    )
    return {"message": "로그아웃되었습니다."}


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> User:
    return user
