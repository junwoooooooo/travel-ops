from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.trips.models import Trip
from app.trips.schemas import TripCreate, TripUpdate


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
