"""테스트는 개발 DB를 건드리지 않는다. travelops_test를 따로 쓰고 매 테스트마다 비운다."""

import asyncio
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth import models as auth_models  # noqa: F401  Base.metadata에 users 등록
from app.config import settings
from app.core.db import Base, get_db
from app.main import app

TEST_DB_NAME = "travelops_test"

# 문자열을 자르지 않고 URL 객체로 파생시킨다 — .env 하나로 로컬·CI 모두 성립한다
_url = make_url(settings.database_url)
TEST_DB_URL = _url.set(database=TEST_DB_NAME)
ADMIN_DB_URL = _url.set(database="postgres")


async def _create_test_database() -> None:
    """CREATE DATABASE는 트랜잭션 안에서 못 돈다 — AUTOCOMMIT으로 붙는다."""
    engine = create_async_engine(ADMIN_DB_URL, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            exists = await conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": TEST_DB_NAME},
            )
            if exists.scalar() is None:
                # 식별자는 바인딩이 안 된다. TEST_DB_NAME은 이 파일의 상수라 주입 경로가 없다
                await conn.execute(text(f'CREATE DATABASE "{TEST_DB_NAME}"'))
    finally:
        await engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def test_database() -> None:
    asyncio.run(_create_test_database())


@pytest.fixture
async def db_session(test_database: None) -> AsyncGenerator[AsyncSession, None]:
    """테이블을 매 테스트마다 새로 판다. 테스트 간 순서 의존성을 원천 차단한다."""
    engine = create_async_engine(TEST_DB_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """ASGITransport는 서버를 띄우지 않고 앱을 직접 호출한다.

    lifespan을 돌리지 않으므로 main.py의 create_all이 개발 DB에 실행될 일이 없다.
    """

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as async_client:
        yield async_client
    app.dependency_overrides.clear()
