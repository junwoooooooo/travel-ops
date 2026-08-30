from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.auth.router import router as auth_router
from app.config import settings
from app.core.db import engine
from app.trips.router import router as trips_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """스키마는 여기서 만들지 않는다.

    Phase 0에는 create_all이 있었다. 이제 테이블은 마이그레이션으로만 생기고
    (`alembic upgrade head`), 앱은 이미 맞춰진 DB에 붙는다 (ADR-0007).
    """
    yield
    await engine.dispose()


app = FastAPI(title="Travel Ops", version="0.1.0", lifespan=lifespan)

app.include_router(auth_router)
app.include_router(trips_router)


@app.get("/health", tags=["ops"])
async def health() -> dict[str, str]:
    """살아있는지 + 어느 커밋이 떠 있는지.

    commit이 있어야 배포 검증이 "200이 온다"가 아니라 "이 커밋이 떠 있다"를 판정할 수 있다.
    서버에 들어가지 않고 밖에서 curl 한 번으로 확인된다.
    """
    return {"status": "ok", "commit": settings.git_sha}
