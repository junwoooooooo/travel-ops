"""Alembic 실행 환경. 어떤 DB에 붙고 어떤 모델과 대조할지를 여기서만 정한다."""

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context
from app.auth import models as auth_models  # noqa: F401  Base.metadata에 users 등록
from app.config import settings
from app.core.db import Base
from app.trips import models as trips_models  # noqa: F401  Base.metadata에 trips 등록

# 도메인 models를 여기서 한 줄씩 명시 import한다. 빠뜨리면 autogenerate가 그 테이블을
# "지워야 할 것"으로 읽는다. core가 도메인을 대신 import하는 헬퍼는 만들지 않는다 —
# 의존 방향(도메인 → core)이 뒤집힌다 (ROADMAP 4장 규칙 3).

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url() -> str:
    """평소엔 .env. 드리프트 테스트만 임시 DB를 attributes로 주입한다.

    ini의 sqlalchemy.url이 아니라 attributes를 쓰는 이유: ini 값은 configparser 보간을
    거쳐서 비밀번호에 %가 들어가면 조용히 깨진다.
    """
    return config.attributes.get("db_url") or settings.database_url


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # 컬럼 타입 변경도 감지 대상에 넣는다. 기본값은 이름·존재 여부만 본다
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = create_async_engine(get_url(), poolclass=pool.NullPool)

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_offline() -> None:
    """--sql 모드. DB에 붙지 않고 SQL만 뽑는다 (배포 전 검토용)."""
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())
