from datetime import date, datetime, time, timedelta
from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    model_validator,
)


class TripCreate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    destination: str = Field(min_length=1, max_length=120)
    start_date: date
    end_date: date
    # 원 단위 정수. 없으면 "예산 미정"이지 0원이 아니다
    budget_total: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def check_date_order(self) -> Self:
        if self.end_date < self.start_date:
            raise ValueError("end_date must not be earlier than start_date")
        return self


class TripUpdate(BaseModel):
    """부분 수정. 보내지 않은 필드는 건드리지 않는다."""

    title: str | None = Field(default=None, min_length=1, max_length=120)
    destination: str | None = Field(default=None, min_length=1, max_length=120)
    start_date: date | None = None
    end_date: date | None = None
    budget_total: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def check_date_order(self) -> Self:
        """두 날짜가 함께 올 때만 여기서 판정한다.

        한쪽만 오면 저장된 값과 합쳐봐야 알 수 있다 — 그건 service의 몫이다.
        """
        if self.start_date is not None and self.end_date is not None:
            if self.end_date < self.start_date:
                raise ValueError("end_date must not be earlier than start_date")
        return self


class TripRead(BaseModel):
    """user_id는 담지 않는다. 어차피 자기 것만 보이므로 정보량이 0이고 노출만 는다."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    destination: str
    start_date: date
    end_date: date
    budget_total: int | None
    created_at: datetime
    updated_at: datetime


# 한 여행의 일정을 통째로 받으므로 상한이 없으면 공짜 DoS다
MAX_BLOCKS_PER_TRIP = 200
# Plan B는 2곳. 개수는 정책이라 여기 있고, DB는 "배열인가"만 본다 (ADR-0009)
MAX_ALTERNATES = 2


class AlternatePlace(BaseModel):
    """블록에 딸린 Plan B 한 곳. blocks.alternates JSONB 원소의 모양 계약이다.

    본체 place_*와 같은 키를 쓴다 — 현장에서 대안으로 갈아탈 때 그대로 옮겨 담는다.
    """

    place_id: str = Field(min_length=1, max_length=64)
    place_name: str = Field(min_length=1, max_length=120)
    place_category: str | None = Field(default=None, max_length=40)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)

    @model_validator(mode="after")
    def check_coords_paired(self) -> Self:
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must be given together")
        return self


class BlockCreate(BaseModel):
    """일정 한 칸의 입력. verified_at은 여기 없다 — 클라이언트가 주장할 값이 아니라
    영업정보를 실제로 확인한 쪽이 남기는 기록이다 (Phase 5).
    """

    day_index: int = Field(ge=1)
    start_time: time
    duration_min: int = Field(gt=0)
    slack_min: int = Field(default=0, ge=0)

    place_id: str = Field(min_length=1, max_length=64)
    place_name: str = Field(min_length=1, max_length=120)
    place_category: str | None = Field(default=None, max_length=40)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)

    priority: Literal["anchor", "filler"]
    booking: Literal["none", "required"] = "none"
    booking_confirmed: bool = False
    cost: int | None = Field(default=None, ge=0)

    alternates: list[AlternatePlace] = Field(
        default_factory=list, max_length=MAX_ALTERNATES
    )

    @model_validator(mode="after")
    def check_cross_field_rules(self) -> Self:
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must be given together")
        if self.booking == "none" and self.booking_confirmed:
            raise ValueError("booking_confirmed requires booking='required'")
        return self


class BlockRead(BaseModel):
    """trip_id는 담지 않는다. URL이 이미 말하고 있다 (TripRead가 user_id를 뺀 것과 같다)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    day_index: int
    start_time: time
    duration_min: int
    slack_min: int

    place_id: str
    place_name: str
    place_category: str | None
    latitude: float | None
    longitude: float | None

    priority: str
    booking: str
    booking_confirmed: bool
    cost: int | None

    alternates: list[AlternatePlace]
    verified_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def end_time(self) -> time:
        """저장하지 않고 계산한다. 자정을 넘으면 그냥 돌아간다 — 23:00 + 120분 = 01:00."""
        base = datetime.combine(date.min, self.start_time)
        return (base + timedelta(minutes=self.duration_min)).time()
