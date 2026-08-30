"""create trips

users 1:N trips. 소유자(user_id)로만 조회되는 테이블이라 인덱스가 선택이 아니고,
날짜 순서·예산 부호는 CHECK로 DB가 최종 방어선을 잡는다 (R4).

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-30 20:24:08.565499

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "trips",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("destination", sa.String(length=120), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("budget_total", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "budget_total IS NULL OR budget_total >= 0",
            name="ck_trips_budget_non_negative",
        ),
        sa.CheckConstraint("end_date >= start_date", name="ck_trips_date_order"),
        # 회원이 지워지면 그 사람의 여행도 함께 사라진다
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_trips_user_id", "trips", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_trips_user_id", table_name="trips")
    op.drop_table("trips")
