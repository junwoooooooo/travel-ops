"""캐시 설비. 붙잡는 계약은 둘이다 — 값이 온전히 왕복하는 것, 그리고 Redis가 죽어도
요청이 죽지 않는 것.

두 번째가 이 파일의 존재 이유다. 캐시는 있으면 빠르고 없으면 느릴 뿐이어야 하는데,
그 성질은 코드를 읽어서는 확인되지 않고 실제로 죽여 봐야 확인된다.
"""

import json
from collections.abc import AsyncGenerator

import pytest

from app.config import settings
from app.core import cache

KEY = "test:cache:key"

# 아무도 듣고 있지 않은 포트. 접속이 거부되므로 타임아웃을 기다리지 않는다
DEAD_REDIS_URL = "redis://127.0.0.1:6390/0"


@pytest.fixture
async def dead_redis(test_redis_url: None) -> AsyncGenerator[None, None]:
    """캐시가 죽은 Redis를 보게 만든다."""
    original = settings.redis_url
    settings.redis_url = DEAD_REDIS_URL
    cache._client = None
    yield
    await cache.aclose()
    settings.redis_url = original


async def test_a_value_survives_a_roundtrip(redis_cache: None) -> None:
    """한글이 그대로 돌아와야 한다 — 여행 제목·장소명이 전부 한국어다."""
    await cache.set_json(KEY, {"장소": "감천문화마을", "비용": 0}, ttl_seconds=60)

    assert await cache.get_json(KEY) == {"장소": "감천문화마을", "비용": 0}


async def test_a_missing_key_is_none(redis_cache: None) -> None:
    assert await cache.get_json("test:cache:absent") is None


async def test_a_stored_value_carries_a_ttl(redis_cache: None) -> None:
    """TTL이 안 붙으면 캐시가 아니라 영구 저장소가 된다 — 폐업한 가게가 영원히 남는다."""
    await cache.set_json(KEY, ["값"], ttl_seconds=60)

    ttl = await cache._get_client().ttl(KEY)

    assert 0 < ttl <= 60


async def test_a_dead_redis_reads_as_a_miss(dead_redis: None) -> None:
    """이 프로젝트의 장애 격리 계약. 예외가 아니라 None이다."""
    assert await cache.get_json(KEY) is None


async def test_a_dead_redis_swallows_writes(dead_redis: None) -> None:
    """저장 실패는 요청의 실패가 아니다. 아무 일도 일어나지 않아야 한다."""
    await cache.set_json(KEY, {"아무": "값"}, ttl_seconds=60)


async def test_a_corrupt_cached_value_is_not_swallowed(redis_cache: None) -> None:
    """RedisError만 삼킨다는 결정을 붙잡는다.

    JSON이 깨진 것은 업스트림 장애가 아니라 우리가 저장한 값이 이상하다는 뜻이다.
    이걸 조용히 미스로 처리하면 원인을 영영 못 찾는다.
    """
    await cache._get_client().set(KEY, "이건 JSON이 아니다")

    with pytest.raises(json.JSONDecodeError):
        await cache.get_json(KEY)
