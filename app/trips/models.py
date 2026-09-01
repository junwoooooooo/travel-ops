from datetime import date, datetime, time
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Double,
    ForeignKey,
    String,
    Time,
    false,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.mutable import MutableList
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Trip(Base):
    """여행 한 건. 계획(blocks)이 아니라 여행 자체의 테두리 — 어디를·언제·얼마로."""

    __tablename__ = "trips"
    __table_args__ = (
        # 파이썬 검증이 뚫려도 여기서 막힌다. auth의 email unique와 같은 역할 —
        # 제약은 최종 방어선이지 유일한 방어선이 아니다 (R4)
        CheckConstraint("end_date >= start_date", name="ck_trips_date_order"),
        CheckConstraint(
            "budget_total IS NULL OR budget_total >= 0",
            name="ck_trips_budget_non_negative",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # 남의 도메인 테이블은 문자열로만 가리킨다. app.auth.models.User를 import하지도,
    # relationship()을 걸지도 않는다 (CLAUDE.md 절대 규칙).
    # 조회가 항상 이 컬럼으로 걸러지므로 인덱스는 선택이 아니다
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(120))
    destination: Mapped[str] = mapped_column(String(120))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    # 원 단위 정수. 돈에 float를 쓰면 합계가 조용히 틀어진다 (R4)
    budget_total: Mapped[int | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Block(Base):
    """여행 하루 안의 "머무는 곳" 한 칸.

    이동은 블록이 아니다 — 연속한 두 블록 사이에서 계산되는 결과다. 이동을 행으로
    만들면 일자별 비용 합계도 압축 엔진도 대안 목록도 의미가 한꺼번에 바뀐다.

    place_*는 "지금 이 장소가 어떤가"가 아니라 "계획할 때 이렇게 기록했다"는 스냅샷이다.
    가게가 이름을 바꾸거나 문을 닫아도 이 행은 그대로 남아야 감시(Phase 5)가 무엇과
    무엇을 비교하는지 말할 수 있다. 그래서 places 테이블로 정규화하지 않는다 (ADR-0009).

    day_index는 1-based. "2일차"가 곧 2다. 실제 날짜는 trips.start_date + (day_index - 1)
    로 계산한다 — 날짜를 복제해 두면 여행 날짜를 하루 미룰 때 전부 조용히 어긋난다.
    """

    __tablename__ = "blocks"
    __table_args__ = (
        # 파이썬 검증이 뚫려도 여기서 막힌다 — Trip과 같은 기준이다 (R4)
        CheckConstraint("day_index >= 1", name="ck_blocks_day_index_positive"),
        CheckConstraint("duration_min > 0", name="ck_blocks_duration_positive"),
        CheckConstraint("slack_min >= 0", name="ck_blocks_slack_non_negative"),
        CheckConstraint("cost IS NULL OR cost >= 0", name="ck_blocks_cost_non_negative"),
        # 이 프로젝트의 환각 차단 계약. 빈 문자열은 place_id가 없는 것과 같다
        CheckConstraint("length(place_id) > 0", name="ck_blocks_place_id_not_blank"),
        # 네이티브 ENUM 대신 CHECK다. 값 목록의 원본은 schemas의 Literal이고
        # 여기는 최종 방어선이다 (ADR-0009)
        CheckConstraint("priority IN ('anchor', 'filler')", name="ck_blocks_priority"),
        CheckConstraint("booking IN ('none', 'required')", name="ck_blocks_booking"),
        # 필요하지도 않은 예약을 확정할 수는 없다
        CheckConstraint(
            "booking = 'required' OR booking_confirmed IS false",
            name="ck_blocks_confirmed_requires_booking",
        ),
        # 좌표는 반쪽이면 쓸모가 없다 — 도보권 판정도 이동시간도 못 한다
        CheckConstraint(
            "(latitude IS NULL) = (longitude IS NULL)", name="ck_blocks_coords_paired"
        ),
        CheckConstraint(
            "latitude IS NULL OR latitude BETWEEN -90 AND 90",
            name="ck_blocks_latitude_range",
        ),
        CheckConstraint(
            "longitude IS NULL OR longitude BETWEEN -180 AND 180",
            name="ck_blocks_longitude_range",
        ),
        # 원소의 모양은 Pydantic이, 통의 모양은 DB가 본다
        CheckConstraint(
            "jsonb_typeof(alternates) = 'array'", name="ck_blocks_alternates_is_array"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # Trip과 같은 이유로 문자열 참조 + 인덱스. 여행이 지워지면 일정도 함께 사라진다
    trip_id: Mapped[int] = mapped_column(
        ForeignKey("trips.id", ondelete="CASCADE"), index=True
    )

    day_index: Mapped[int]
    # 시간대가 없는 현지 벽시계다. 오사카의 09:00은 그냥 09:00이고, UTC로 굳히면
    # Phase 2의 운영시간 검증이 몇 시간씩 틀린다. timetz는 쓰지 않는다
    start_time: Mapped[time] = mapped_column(Time)
    # end_time이 아니라 길이를 저장한다. 자정을 넘는 블록(23:00→01:00)을 제약으로
    # 금지하지 않게 되고, 지연 시 이후 시각 재계산이 분 단위 정수 덧셈으로 끝난다
    duration_min: Mapped[int]
    # 이 블록 "뒤"의 여유. 압축 엔진이 지연을 먼저 갉아먹는 곳이다
    slack_min: Mapped[int] = mapped_column(server_default=text("0"))

    place_id: Mapped[str] = mapped_column(String(64))
    place_name: Mapped[str] = mapped_column(String(120))
    # Plan B는 "같은 카테고리"로 고른다. 나중에 다시 조회하면 그때 값이지 이때 값이 아니다
    place_category: Mapped[str | None] = mapped_column(String(40), default=None)
    # 돈이 아니라 측정값이라 float8이다. cost에 Numeric을 안 쓰고 정수를 쓴 것과
    # 같은 기준 — 합계가 틀어지면 안 되는 값과 소수점 이하 1e-9도 안에서 정확하면
    # 되는 값은 다르다. alternates JSONB에도 같은 모양으로 들어간다
    latitude: Mapped[float | None] = mapped_column(Double, default=None)
    longitude: Mapped[float | None] = mapped_column(Double, default=None)

    # 기본값을 주지 않는다. 지연 시 무엇을 지키고 무엇을 버릴지는 계획을 세운 쪽이
    # 반드시 정해야 하는 판단이고, 정하지 않은 블록은 만들어지면 안 된다
    priority: Mapped[str] = mapped_column(String(16))
    booking: Mapped[str] = mapped_column(String(16), server_default="none")
    booking_confirmed: Mapped[bool] = mapped_column(server_default=false())
    # 원 단위 정수. NULL은 0원이 아니라 "미정"이다 (trips.budget_total과 같은 규약)
    cost: Mapped[int | None] = mapped_column(default=None)

    # MutableList가 없으면 alternates.append(...)를 SQLAlchemy가 보지 못해 저장이
    # 조용히 안 된다. Phase 2의 Plan B 심기가 정확히 그 코드다
    alternates: Mapped[list[dict[str, Any]]] = mapped_column(
        MutableList.as_mutable(JSONB), server_default=text("'[]'::jsonb")
    )
    # NULL은 "아직 한 번도 검증된 적 없음"이다. now()를 기본값으로 주면 아무것도
    # 확인하지 않고 확인했다고 기록하는 셈이라, 재검증 대상 조회가 전부 거짓이 된다
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
