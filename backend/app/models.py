"""데이터 모델 — 이 파일이 스키마의 단일 진실 공급원(source of truth).

핵심 설계: **잔액 컬럼은 없다.** 식당 잔액은 언제나 transactions 원장의 합으로 계산한다.
    balance = Σ(CHARGE) − Σ(USE) + Σ(ADJUST)   (voided_at IS NULL 인 것만)
기록은 삭제하지 않고 void(사유 필수) 처리해 감사 추적을 남긴다.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    case,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.core.timeutil import utc_now


class UserRole(str, enum.Enum):
    admin = "admin"
    member = "member"


class TxType(str, enum.Enum):
    CHARGE = "CHARGE"  # 선결제 충전 (amount > 0)
    USE = "USE"  # 사용/차감 (amount > 0, 잔액에서 뺀다)
    ADJUST = "ADJUST"  # 정정 (amount 부호 있음, 0 불가)


class OcrStatus(str, enum.Enum):
    pending = "pending"
    done = "done"
    failed = "failed"


def _enum(py_enum: type[enum.Enum], length: int = 16) -> Enum:
    """DB 네이티브 ENUM 대신 VARCHAR + CHECK 로 저장 (SQLite/PG 모두 안전, 마이그레이션 쉬움)."""
    return Enum(py_enum, native_enum=False, length=length, validate_strings=True)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(_enum(UserRole), default=UserRole.member, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)

    @property
    def is_admin(self) -> bool:
        return self.role == UserRole.admin


class Restaurant(Base):
    __tablename__ = "restaurants"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), index=True, nullable=False)
    # 사업자등록번호: 숫자 10자리만 정규화 저장. 영수증 매칭의 1순위 키.
    # NULL 허용 (수동 등록 시 모를 수 있음) — SQLite/PG 모두 NULL 은 unique 중복 허용.
    business_number: Mapped[str | None] = mapped_column(String(10), unique=True, index=True)
    address: Mapped[str | None] = mapped_column(String(300))
    phone: Mapped[str | None] = mapped_column(String(40))
    memo: Mapped[str | None] = mapped_column(Text)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, onupdate=utc_now, nullable=False
    )

    creator: Mapped[User | None] = relationship(lazy="joined")
    transactions: Mapped[list[Transaction]] = relationship(
        back_populates="restaurant", cascade="all, delete-orphan", passive_deletes=True
    )


class Receipt(Base):
    __tablename__ = "receipts"

    id: Mapped[int] = mapped_column(primary_key=True)
    image_path: Mapped[str] = mapped_column(String(500), nullable=False)
    original_filename: Mapped[str | None] = mapped_column(String(255))
    content_type: Mapped[str | None] = mapped_column(String(100))

    ocr_status: Mapped[OcrStatus] = mapped_column(
        _enum(OcrStatus), default=OcrStatus.pending, nullable=False
    )
    ocr_error: Mapped[str | None] = mapped_column(Text)
    ocr_raw: Mapped[str | None] = mapped_column(Text)  # 모델 원문 응답 (디버깅용)
    ocr_ms: Mapped[int | None] = mapped_column(Integer)  # 소요 시간

    # OCR 이 추출한 값 (사용자가 화면에서 수정 가능 — 확정 시 덮어씀)
    parsed_store_name: Mapped[str | None] = mapped_column(String(200))
    parsed_business_number: Mapped[str | None] = mapped_column(String(10))
    parsed_address: Mapped[str | None] = mapped_column(String(300))
    parsed_phone: Mapped[str | None] = mapped_column(String(40))
    parsed_total_amount: Mapped[int | None] = mapped_column(Integer)  # 부가세 포함 합계 (원)
    parsed_paid_at: Mapped[datetime | None] = mapped_column(DateTime)  # naive UTC

    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    # confirm 이 실행되면 기록 → 같은 영수증으로 두 번 충전/차감되는 것을 막는다
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime)

    uploader: Mapped[User | None] = relationship(lazy="joined")

    __table_args__ = (
        Index("ix_receipts_dup", "parsed_business_number", "parsed_total_amount", "parsed_paid_at"),
    )


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(
        ForeignKey("restaurants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    type: Mapped[TxType] = mapped_column(_enum(TxType), nullable=False)
    # 원 단위 정수. CHARGE/USE 는 양수, ADJUST 는 부호 있는 0 이 아닌 값.
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    memo: Mapped[str | None] = mapped_column(Text)
    receipt_id: Mapped[int | None] = mapped_column(ForeignKey("receipts.id", ondelete="SET NULL"))

    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)

    # 취소(정정) — 삭제하지 않고 무효화 표시
    voided_at: Mapped[datetime | None] = mapped_column(DateTime)
    voided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    void_reason: Mapped[str | None] = mapped_column(Text)

    restaurant: Mapped[Restaurant] = relationship(back_populates="transactions")
    creator: Mapped[User | None] = relationship(foreign_keys=[created_by], lazy="joined")
    voider: Mapped[User | None] = relationship(foreign_keys=[voided_by], lazy="joined")
    receipt: Mapped[Receipt | None] = relationship(lazy="selectin")

    __table_args__ = (
        CheckConstraint("amount <> 0", name="ck_tx_amount_nonzero"),
        Index("ix_tx_restaurant_occurred", "restaurant_id", "occurred_at"),
        Index("ix_tx_occurred", "occurred_at"),
    )

    @property
    def is_voided(self) -> bool:
        return self.voided_at is not None

    @property
    def signed_amount(self) -> int:
        """잔액에 실제로 반영되는 부호 있는 금액."""
        if self.voided_at is not None:
            return 0
        if self.type == TxType.USE:
            return -self.amount
        return self.amount  # CHARGE, ADJUST(이미 부호 있음)


# 잔액 집계용 SQL 표현식 — ledger 서비스와 목록 쿼리에서 재사용한다.
SIGNED_AMOUNT_SQL = case(
    (Transaction.type == TxType.USE, -Transaction.amount),
    else_=Transaction.amount,
)
