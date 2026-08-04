"""인증 스키마 — CONTRACT.md §2.1."""

from __future__ import annotations

import enum
import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import ApiModel, UtcOut

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _enum_value(v: Any) -> Any:
    """ORM 의 Enum 멤버를 Literal 로 검증 가능한 문자열로 바꾼다."""
    return v.value if isinstance(v, enum.Enum) else v


def _normalize_email(v: Any) -> Any:
    """이메일은 소문자 + 트림으로 정규화한다 (중복 판정·로그인 일관성)."""
    if isinstance(v, str):
        v = v.strip().lower()
        if not _EMAIL_RE.match(v):
            raise ValueError("이메일 형식이 올바르지 않습니다.")
    return v


class UserOut(ApiModel):
    id: int
    email: str
    name: str
    role: Literal["admin", "member"]
    is_active: bool
    created_at: UtcOut

    @field_validator("role", mode="before")
    @classmethod
    def _role_value(cls, v: Any) -> Any:
        return _enum_value(v)


class RegisterIn(BaseModel):
    email: str
    name: str = Field(min_length=1, max_length=100)
    # 비밀번호 길이(8자) 검증은 라우터에서 한국어 메시지로 처리한다
    # (pydantic 기본 메시지는 영어 + detail 이 배열이 되어 프론트 노출에 부적합)
    password: str = Field(min_length=1, max_length=200)
    invite_code: str = Field(min_length=1)

    @field_validator("email", mode="before")
    @classmethod
    def _email(cls, v: Any) -> Any:
        return _normalize_email(v)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("이름을 입력해 주세요.")
        return v


class LoginIn(BaseModel):
    email: str
    password: str = Field(min_length=1, max_length=200)

    @field_validator("email", mode="before")
    @classmethod
    def _email(cls, v: Any) -> Any:
        return _normalize_email(v)


class UserUpdateIn(BaseModel):
    """관리자용 사용자 수정 — 전부 optional (보낸 필드만 반영)."""

    name: str | None = Field(default=None, max_length=100)
    role: Literal["admin", "member"] | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, max_length=200)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            raise ValueError("이름을 입력해 주세요.")
        return v
