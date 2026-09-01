"""create blocks

trips 1:N blocks. 여행의 테두리(0002) 안에 내용물이 들어간다.

이 테이블이 저장하는 것은 "지금 이 장소가 어떤가"가 아니라 "계획할 때 이렇게
기록했다"는 스냅샷이다. 그래서 place_*를 별도 테이블로 정규화하지 않는다 —
정규화하면 나중에 그 행을 갱신하는 순간 계획이 무엇을 보고 만들어졌는지가 지워지고,
감시(Phase 5)가 비교할 좌변이 사라진다 (ADR-0009).

시각은 여행에 대한 상대 좌표다(day_index + start_time + duration_min). 절대 날짜를
복제하면 여행 날짜를 하루 미룰 때 모든 블록이 조용히 어긋나는데, 그 불변식은 다른
테이블을 참조해야 해서 CHECK로 표현할 수 없다.

CHECK가 열둘인 이유는 이 테이블이 이 프로젝트가 "틀리면 안 되는 것"이라 부르는
값들(예산·시간·실존 장소)을 처음으로 한자리에 모으기 때문이다 (R4). 특히
ck_blocks_place_id_not_blank가 환각 차단 계약의 실체다. 값 목록은 네이티브 ENUM이
아니라 CHECK로 적는다 — autogenerate가 enum 값 변경을 감지하지 못해 드리프트
게이트를 그대로 통과하고, drop_table이 타입을 남겨서 downgrade 왕복도 깨진다.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-01 13:59:29.903508

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "blocks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("trip_id", sa.Integer(), nullable=False),
        sa.Column("day_index", sa.Integer(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("duration_min", sa.Integer(), nullable=False),
        sa.Column(
            "slack_min", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("place_id", sa.String(length=64), nullable=False),
        sa.Column("place_name", sa.String(length=120), nullable=False),
        sa.Column("place_category", sa.String(length=40), nullable=True),
        sa.Column("latitude", sa.Double(), nullable=True),
        sa.Column("longitude", sa.Double(), nullable=True),
        sa.Column("priority", sa.String(length=16), nullable=False),
        sa.Column(
            "booking", sa.String(length=16), server_default="none", nullable=False
        ),
        sa.Column(
            "booking_confirmed",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("cost", sa.Integer(), nullable=True),
        sa.Column(
            "alternates",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint("day_index >= 1", name="ck_blocks_day_index_positive"),
        sa.CheckConstraint("duration_min > 0", name="ck_blocks_duration_positive"),
        sa.CheckConstraint("slack_min >= 0", name="ck_blocks_slack_non_negative"),
        sa.CheckConstraint(
            "cost IS NULL OR cost >= 0", name="ck_blocks_cost_non_negative"
        ),
        # 환각 차단 계약. 빈 문자열은 place_id가 없는 것과 같다
        sa.CheckConstraint("length(place_id) > 0", name="ck_blocks_place_id_not_blank"),
        sa.CheckConstraint(
            "priority IN ('anchor', 'filler')", name="ck_blocks_priority"
        ),
        sa.CheckConstraint("booking IN ('none', 'required')", name="ck_blocks_booking"),
        sa.CheckConstraint(
            "booking = 'required' OR booking_confirmed IS false",
            name="ck_blocks_confirmed_requires_booking",
        ),
        sa.CheckConstraint(
            "(latitude IS NULL) = (longitude IS NULL)", name="ck_blocks_coords_paired"
        ),
        sa.CheckConstraint(
            "latitude IS NULL OR latitude BETWEEN -90 AND 90",
            name="ck_blocks_latitude_range",
        ),
        sa.CheckConstraint(
            "longitude IS NULL OR longitude BETWEEN -180 AND 180",
            name="ck_blocks_longitude_range",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(alternates) = 'array'", name="ck_blocks_alternates_is_array"
        ),
        # 여행이 지워지면 그 일정도 함께 사라진다 (users → trips → blocks 2단 체인)
        sa.ForeignKeyConstraint(["trip_id"], ["trips.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_blocks_trip_id", "blocks", ["trip_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_blocks_trip_id", table_name="blocks")
    op.drop_table("blocks")
