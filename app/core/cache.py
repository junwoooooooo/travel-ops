"""캐시는 요청을 죽이지 않는다. Redis가 없으면 전부 미스처럼 행동한다.

설비다. 도메인이 아니라 db.py·security.py와 같은 층에 산다.
"""

import json
import logging
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.config import settings

logger = logging.getLogger(__name__)

# 캐시가 느리면 존재 이유가 없다. Redis가 죽었을 때 조회가 요청을 붙잡으면
# 캐시는 성능 개선이 아니라 장애 증폭기가 된다 — 그래서 소켓 타임아웃을 아주 짧게 건다.
# DB 커넥션(수 초)과 같은 숫자를 쓰면 안 되는 이유다
_SOCKET_TIMEOUT_SECONDS = 0.2

_client: Redis | None = None


def _get_client() -> Redis:
    """지연 생성 싱글턴. import 시점에는 접속하지 않는다.

    모듈을 읽는 것만으로 Redis를 요구하면 Redis 없는 환경에서 pytest 수집조차 못 한다.
    """
    global _client
    if _client is None:
        _client = Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_timeout=_SOCKET_TIMEOUT_SECONDS,
            socket_connect_timeout=_SOCKET_TIMEOUT_SECONDS,
        )
    return _client


async def get_json(key: str) -> Any | None:
    """캐시에 있으면 그 값, 없거나 Redis가 아프면 None.

    호출자는 "미스"와 "Redis 장애"를 구별하지 않는다 — 둘 다 원본을 부르면 되기 때문이다.
    """
    try:
        raw = await _get_client().get(key)
    except RedisError:
        # Exception이 아니라 RedisError만 삼킨다. 아래 json 디코드 실패는 업스트림 장애가
        # 아니라 우리가 저장한 값이 깨졌다는 뜻이라, 조용히 넘기면 원인을 영영 못 찾는다
        logger.warning("캐시 조회 실패 — 미스로 처리한다 (key=%s)", key)
        return None

    if raw is None:
        return None
    return json.loads(raw)


async def set_json(key: str, value: Any, ttl_seconds: int) -> None:
    """저장에 실패해도 호출자는 모른다. 캐시 쓰기는 요청의 성공 조건이 아니다."""
    try:
        # ensure_ascii=False — 데이터가 한국어다. 이스케이프하면 저장 용량만 3배가 된다
        await _get_client().set(
            key, json.dumps(value, ensure_ascii=False), ex=ttl_seconds
        )
    except RedisError:
        logger.warning("캐시 저장 실패 — 무시한다 (key=%s)", key)


async def aclose() -> None:
    """lifespan 종료용. 다음 호출이 새 클라이언트를 만들도록 전역도 비운다."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
