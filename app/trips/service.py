from collections.abc import Sequence

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.trips.models import Block, Trip
from app.trips.schemas import (
    MAX_BLOCKS_PER_TRIP,
    BlockCreate,
    TripCreate,
    TripUpdate,
)


class InvalidDateRange(ValueError):
    """수정 결과가 end_date < start_date가 되는 경우. HTTP 변환은 router 몫이다."""


async def create_trip(db: AsyncSession, owner_id: int, payload: TripCreate) -> Trip:
    trip = Trip(user_id=owner_id, **payload.model_dump())
    db.add(trip)
    await db.commit()
    await db.refresh(trip)
    return trip


async def list_trips(db: AsyncSession, owner_id: int) -> Sequence[Trip]:
    """다가오는 여행이 위로. 같은 날짜면 나중에 만든 것이 위로."""
    result = await db.execute(
        select(Trip)
        .where(Trip.user_id == owner_id)
        .order_by(Trip.start_date.desc(), Trip.id.desc())
    )
    return result.scalars().all()


async def get_trip(db: AsyncSession, trip_id: int, owner_id: int) -> Trip | None:
    """소유자 조건이 WHERE에 있다 — 찾은 뒤에 비교하지 않는다.

    "없는 여행"과 "남의 여행"이 코드 경로에서부터 구별되지 않아야
    응답이 실수로 갈라지지 않는다 (CLAUDE.md: 소유권 위반은 404).
    """
    result = await db.execute(
        select(Trip).where(Trip.id == trip_id, Trip.user_id == owner_id)
    )
    return result.scalar_one_or_none()


async def update_trip(db: AsyncSession, trip: Trip, payload: TripUpdate) -> Trip:
    changes = payload.model_dump(exclude_unset=True)

    # 날짜 한쪽만 바뀌는 경우는 스키마가 못 잡는다. 저장값과 합친 결과로 판정한다
    start = changes.get("start_date", trip.start_date)
    end = changes.get("end_date", trip.end_date)
    if end < start:
        raise InvalidDateRange("end_date must not be earlier than start_date")

    for field, value in changes.items():
        setattr(trip, field, value)

    await db.commit()
    await db.refresh(trip)
    return trip


async def delete_trip(db: AsyncSession, trip: Trip) -> None:
    await db.delete(trip)
    await db.commit()


class InvalidBlockPlan(ValueError):
    """일정 자체가 자기모순이다(겹침·개수 초과). HTTP 변환은 router 몫이다."""


def _reject_overlaps(payload: Sequence[BlockCreate]) -> None:
    """같은 날 두 블록이 겹치면 거부한다.

    "한 사람이 두 곳에 동시에 있다"는 검증 실패가 아니라 자기모순 데이터다 —
    예산 초과·이동시간 부족처럼 사람이 판단할 여지가 있는 것(Phase 2 validate)과
    성격이 다르다. 여기서 막으면 start_time이 그날 안에서 유일해지고,
    (day_index, start_time) 정렬이 곧 일정 순서가 된다 — order_index가 따로 필요 없다.

    분 단위 정수로 다룬다. 자정을 넘는 블록은 끝이 1440을 넘을 뿐이라 계산이 그대로 된다
    (다음 날 첫 블록과의 겹침까지 보지는 않는다 — day_index 안에서만 판정한다).
    """
    by_day: dict[int, list[tuple[int, int]]] = {}
    for block in payload:
        start = block.start_time.hour * 60 + block.start_time.minute
        by_day.setdefault(block.day_index, []).append(
            (start, start + block.duration_min)
        )

    for day, spans in by_day.items():
        spans.sort()
        for (_, prev_end), (start, _) in zip(spans, spans[1:]):
            if start < prev_end:
                raise InvalidBlockPlan(f"blocks overlap on day {day}")


async def list_blocks(db: AsyncSession, trip_id: int) -> Sequence[Block]:
    """(일자, 시작시각) 순. 같은 시각은 겹침 검사가 막으므로 id는 최후의 결정자일 뿐이다."""
    result = await db.execute(
        select(Block)
        .where(Block.trip_id == trip_id)
        .order_by(Block.day_index, Block.start_time, Block.id)
    )
    return result.scalars().all()


async def replace_blocks(
    db: AsyncSession, trip_id: int, payload: Sequence[BlockCreate]
) -> Sequence[Block]:
    """여행의 일정 전체를 교체한다. 블록을 쓰는 쪽은 사람이 아니라 플래너이고,
    플래너는 일정을 한 칸씩이 아니라 통째로 내놓는다. 겹침 같은 집합 불변식도
    전량 쓰기에서 한 번에 판정된다.

    trip_id는 이미 소유권을 통과한 값이다 — 인가는 router의 의존성 한 곳에만 있다.
    """
    if len(payload) > MAX_BLOCKS_PER_TRIP:
        raise InvalidBlockPlan(
            f"a trip cannot hold more than {MAX_BLOCKS_PER_TRIP} blocks"
        )
    _reject_overlaps(payload)

    await db.execute(delete(Block).where(Block.trip_id == trip_id))
    db.add_all(
        [
            Block(
                trip_id=trip_id,
                **(block.model_dump(exclude={"alternates"})),
                alternates=[place.model_dump() for place in block.alternates],
            )
            for block in payload
        ]
    )
    await db.commit()

    # 커밋 직후의 객체는 서버 기본값(created_at 등)이 아직 로드되지 않은 상태일 수 있고,
    # async에서 그걸 건드리면 MissingGreenlet으로 죽는다. 재조회하면 정렬도 공짜다
    return await list_blocks(db, trip_id)
