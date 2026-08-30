from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.service import CurrentUser
from app.core.db import DbSession
from app.trips import service
from app.trips.models import Trip
from app.trips.schemas import TripCreate, TripRead, TripUpdate

router = APIRouter(prefix="/trips", tags=["trips"])

_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND,
    detail="Trip not found",
)


async def get_owned_trip(trip_id: int, current_user: CurrentUser, db: DbSession) -> Trip:
    """내 여행이 아니면 없는 것과 똑같이 404. 403은 "있긴 있다"를 알려준다."""
    trip = await service.get_trip(db, trip_id, current_user.id)
    if trip is None:
        raise _NOT_FOUND
    return trip


OwnedTrip = Annotated[Trip, Depends(get_owned_trip)]


@router.post("", response_model=TripRead, status_code=status.HTTP_201_CREATED)
async def create_trip(
    payload: TripCreate,
    current_user: CurrentUser,
    db: DbSession,
) -> Trip:
    return await service.create_trip(db, current_user.id, payload)


@router.get("", response_model=list[TripRead])
async def list_trips(current_user: CurrentUser, db: DbSession) -> Sequence[Trip]:
    return await service.list_trips(db, current_user.id)


@router.get("/{trip_id}", response_model=TripRead)
async def read_trip(trip: OwnedTrip) -> Trip:
    return trip


@router.patch("/{trip_id}", response_model=TripRead)
async def update_trip(payload: TripUpdate, trip: OwnedTrip, db: DbSession) -> Trip:
    try:
        return await service.update_trip(db, trip, payload)
    except service.InvalidDateRange as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc


@router.delete("/{trip_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_trip(trip: OwnedTrip, db: DbSession) -> None:
    await service.delete_trip(db, trip)
