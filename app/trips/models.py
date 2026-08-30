from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, String, func
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
