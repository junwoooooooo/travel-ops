"""baseline users

Phase 0의 users를 마이그레이션 이력의 출발점으로 삼는다.

이 리비전에만 있는 예외: upgrade()가 users의 존재를 먼저 확인하고, 이미 있으면 아무것도
하지 않는다. Phase 0에서는 앱 시작 시 create_all이 테이블을 만들었기 때문에, 로컬 개발
DB와 배포된 서버 DB에는 users가 이미 있다. 조건 없이 create_table을 실행하면 첫 배포가
"relation users already exists"로 죽고, 사람이 SSH로 들어가 alembic stamp를 쳐야 한다 —
"push하면 반영된다"(Phase 0 DoD)가 깨진다.

0002부터는 이런 분기가 없다. 조건부 마이그레이션은 "이력이 없던 DB를 이력에 편입시키는"
이 한 번에만 정당하다. (ADR-0007)

Revision ID: 0001
Revises:
Create Date: 2026-08-30 20:23:41.222738

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if "users" in sa.inspect(op.get_bind()).get_table_names():
        # create_all이 이미 만든 DB. 이 리비전은 "따라잡기"이므로 건너뛴다
        return

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
