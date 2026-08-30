from datetime import date, datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


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
