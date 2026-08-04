"""관리 라우터 — CONTRACT.md §2.6. 전부 admin 전용 (그 외 403)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.core.config import settings
from app.core.deps import AdminUser, DbSession
from app.core.security import hash_password
from app.models import User, UserRole
from app.schemas.auth import UserOut, UserUpdateIn

router = APIRouter()

MIN_PASSWORD_LENGTH = 8


@router.get("/users", response_model=list[UserOut])
def list_users(admin: AdminUser, db: DbSession) -> list[User]:
    return list(db.execute(select(User).order_by(User.id.asc())).scalars().all())


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: int, payload: UserUpdateIn, admin: AdminUser, db: DbSession
) -> User:
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="사용자를 찾을 수 없습니다."
        )

    changes = payload.model_dump(exclude_unset=True)  # 보낸 필드만 반영

    # 마지막 관리자 잠금 방지: 본인의 권한 강등·계정 비활성화는 막는다
    if target.id == admin.id:
        if changes.get("role") == UserRole.member.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="본인의 관리자 권한은 해제할 수 없습니다.",
            )
        if changes.get("is_active") is False:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="본인 계정을 비활성화할 수 없습니다.",
            )

    if "password" in changes:
        password = changes.pop("password")
        if password is not None:
            if len(password) < MIN_PASSWORD_LENGTH:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=f"비밀번호는 {MIN_PASSWORD_LENGTH}자 이상이어야 합니다.",
                )
            target.password_hash = hash_password(password)

    if changes.get("name") is not None:
        target.name = changes["name"]
    if changes.get("role") is not None:
        target.role = UserRole(changes["role"])
    if changes.get("is_active") is not None:
        target.is_active = bool(changes["is_active"])

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(target)
    return target


@router.get("/invite-code", response_model=dict[str, str])
def invite_code(admin: AdminUser) -> dict[str, str]:
    return {"invite_code": settings.invite_code}
