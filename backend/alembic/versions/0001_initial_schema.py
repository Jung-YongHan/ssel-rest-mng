"""initial schema — users / restaurants / receipts / transactions

`app/models.py` 와 1:1 로 맞춘 손수 작성 마이그레이션.
Enum 은 DB 네이티브 ENUM 대신 VARCHAR(16) 로 저장한다 (models._enum 과 동일).

Revision ID: 0001
Revises: None
Create Date: 2026-08-04

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── users ─────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # ── restaurants ───────────────────────────────────────────────
    op.create_table(
        "restaurants",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        # 사업자등록번호: 숫자 10자리 정규화 저장. NULL 은 중복 허용.
        sa.Column("business_number", sa.String(length=10), nullable=True),
        sa.Column("address", sa.String(length=300), nullable=True),
        sa.Column("phone", sa.String(length=40), nullable=True),
        sa.Column("memo", sa.Text(), nullable=True),
        sa.Column("is_archived", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_restaurants_business_number", "restaurants", ["business_number"], unique=True
    )
    op.create_index("ix_restaurants_name", "restaurants", ["name"], unique=False)

    # ── receipts ──────────────────────────────────────────────────
    op.create_table(
        "receipts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("image_path", sa.String(length=500), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=True),
        sa.Column("content_type", sa.String(length=100), nullable=True),
        sa.Column("ocr_status", sa.String(length=16), nullable=False),
        sa.Column("ocr_error", sa.Text(), nullable=True),
        sa.Column("ocr_raw", sa.Text(), nullable=True),
        sa.Column("ocr_ms", sa.Integer(), nullable=True),
        sa.Column("parsed_store_name", sa.String(length=200), nullable=True),
        sa.Column("parsed_business_number", sa.String(length=10), nullable=True),
        sa.Column("parsed_address", sa.String(length=300), nullable=True),
        sa.Column("parsed_phone", sa.String(length=40), nullable=True),
        sa.Column("parsed_total_amount", sa.Integer(), nullable=True),
        sa.Column("parsed_paid_at", sa.DateTime(), nullable=True),
        sa.Column("uploaded_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["uploaded_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    # 중복 영수증 판정용 복합 인덱스 (사업자번호 + 합계금액 + 결제일시)
    op.create_index(
        "ix_receipts_dup",
        "receipts",
        ["parsed_business_number", "parsed_total_amount", "parsed_paid_at"],
        unique=False,
    )

    # ── transactions ──────────────────────────────────────────────
    op.create_table(
        "transactions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("restaurant_id", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("memo", sa.Text(), nullable=True),
        sa.Column("receipt_id", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("voided_at", sa.DateTime(), nullable=True),
        sa.Column("voided_by", sa.Integer(), nullable=True),
        sa.Column("void_reason", sa.Text(), nullable=True),
        # 금액 0 은 의미가 없다 (CHARGE/USE 는 양수, ADJUST 는 부호 있는 0 이 아닌 값)
        sa.CheckConstraint("amount <> 0", name="ck_tx_amount_nonzero"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["receipt_id"], ["receipts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["restaurant_id"], ["restaurants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["voided_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_transactions_restaurant_id", "transactions", ["restaurant_id"], unique=False
    )
    op.create_index("ix_tx_occurred", "transactions", ["occurred_at"], unique=False)
    op.create_index(
        "ix_tx_restaurant_occurred", "transactions", ["restaurant_id", "occurred_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_tx_restaurant_occurred", table_name="transactions")
    op.drop_index("ix_tx_occurred", table_name="transactions")
    op.drop_index("ix_transactions_restaurant_id", table_name="transactions")
    op.drop_table("transactions")

    op.drop_index("ix_receipts_dup", table_name="receipts")
    op.drop_table("receipts")

    op.drop_index("ix_restaurants_name", table_name="restaurants")
    op.drop_index("ix_restaurants_business_number", table_name="restaurants")
    op.drop_table("restaurants")

    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
