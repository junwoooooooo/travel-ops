from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.auth import models as auth_models  # noqa: F401  Base.metadata에 users 등록
from app.auth.router import router as auth_router
from app.config import settings
from app.core.db import Base, engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Phase 0 한정. 마이그레이션 도구 도입 전까지의 임시 조치.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


app = FastAPI(title="Travel Ops", version="0.1.0", lifespan=lifespan)

app.include_router(auth_router)


@app.get("/health", tags=["ops"])
async def health() -> dict[str, str]:
    """살아있는지 + 어느 커밋이 떠 있는지.

    commit이 있어야 배포 검증이 "200이 온다"가 아니라 "이 커밋이 떠 있다"를 판정할 수 있다.
    서버에 들어가지 않고 밖에서 curl 한 번으로 확인된다.
    """
    return {"status": "ok", "commit": settings.git_sha}
