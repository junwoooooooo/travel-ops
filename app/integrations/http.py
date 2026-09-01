"""외부 API를 부르는 단 하나의 통로. 타임아웃·재시도·캐시가 여기 모여 있다.

이 파일은 **실패를 해석하지 않는다.** 못 받았다는 사실만 예외로 올리고, 그게 치명적인지
무시해도 되는지는 호출자가 정한다 — kakao는 치명적이고 weather는 아니다 (ADR-0010).
"""

import asyncio
import logging
import random
import time
from typing import Any

import httpx

from app.core import cache

logger = logging.getLogger(__name__)

# 사람이 기다리는 시간이다. LLM(수십 초)과 같은 예산을 주면 안 된다 (R1).
# connect는 짧게(붙거나 말거나), read는 조금 길게(응답 생성 시간)
_TIMEOUT = httpx.Timeout(connect=2.0, read=3.0, write=3.0, pool=2.0)

# 최대 3회 시도 = 재시도 2회. 최악 소요는 (2+3)*3 + 백오프 ≈ 16초이고,
# 실제로는 read 타임아웃 3초가 대부분이라 ~10초 안쪽이다.
# 4회로 늘리면 사용자 대기가 선형으로 늘고 살아날 확률은 거의 안 는다
_MAX_ATTEMPTS = 3
_BACKOFF_SECONDS = (0.2, 0.6)
# 같은 순간에 죽은 업스트림을 여러 요청이 동시에 재시도하면 되살아나는 순간 다시 밟는다.
# 지터가 그 동기화를 깬다
_JITTER_SECONDS = 0.1

# 429(쿼터)와 5xx만 재시도한다. 그 외 4xx는 다시 물어도 같은 답이다 —
# 401(키 오류)·400(잘못된 파라미터)을 재시도하면 사용자 대기만 3배가 되고 쿼터도 3배로 탄다
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})

_client: httpx.AsyncClient | None = None


class UpstreamUnavailable(RuntimeError):
    """외부 API에서 결국 JSON을 못 받았다.

    `status_code`는 마지막 응답의 상태다(전송 실패·타임아웃이면 None). 이걸 남기는 이유:
    401은 우리 설정이 틀린 것이고 503은 저쪽이 아픈 것인데, 예외 클래스를 둘로 늘리는
    대신 속성 하나로 구별한다 (R3).
    """

    def __init__(self, name: str, status_code: int | None = None) -> None:
        super().__init__(f"{name} 호출 실패 (status={status_code})")
        self.name = name
        self.status_code = status_code


def _get_client() -> httpx.AsyncClient:
    """지연 생성 싱글턴. 커넥션 풀과 TLS 핸드셰이크를 재사용한다.

    호출마다 AsyncClient를 새로 만들면 매번 TCP+TLS를 다시 맺어서, 캐시로 아낀 시간을
    핸드셰이크로 도로 쓴다. 테스트는 이 전역을 MockTransport 클라이언트로 갈아끼운다.
    """
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=_TIMEOUT)
    return _client


async def fetch_json(
    *,
    name: str,
    url: str,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    cache_key: str | None = None,
    cache_ttl: int | None = None,
) -> Any:
    """캐시 → 호출(재시도 포함) → 캐시 저장. 못 받으면 UpstreamUnavailable.

    `name`은 로그용 이름이다(예: "kakao.search"). **우리 로그에는 url·params·headers를
    넣지 않는다** — 키를 쿼리스트링에 싣는 API가 흔해서, URL을 통째로 찍는 습관 하나가
    "비밀은 .env만"을 깬다 (CLAUDE.md 절대 규칙).

    다만 우리가 안 찍는 것만으로는 부족하다. **httpx 자신의 INFO 로거가 매 요청마다
    전체 URL을 쿼리스트링째로 찍는다**(수동 검증에서 확인했다). uvicorn 기본 로그 레벨이
    INFO라 배포 환경에서도 그대로 나온다. 그래서 진짜 불변식은 로거 설정이 아니라
    **인증값은 반드시 headers로 보낸다**이다 — URL이 어디에 남아도 비밀이 아니게 만든다.
    쿼리스트링 키를 요구하는 업스트림(기상청·OpenWeatherMap)을 붙이는 날, 이 불변식이
    깨지므로 그때는 URL 마스킹이 먼저다 (ADR-0010).
    """
    if cache_key is not None:
        cached = await cache.get_json(cache_key)
        if cached is not None:
            logger.debug("%s 캐시 히트", name)
            return cached

    started = time.perf_counter()
    last_status: int | None = None

    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            response = await _get_client().get(url, params=params, headers=headers)
        except (httpx.TimeoutException, httpx.TransportError):
            # 연결 자체가 안 됐다. 상태코드가 없으므로 last_status는 None으로 둔다
            last_status = None
            logger.warning("%s 전송 실패 (시도 %d/%d)", name, attempt, _MAX_ATTEMPTS)
        else:
            last_status = response.status_code
            if response.is_success:
                payload = response.json()
                elapsed_ms = (time.perf_counter() - started) * 1000
                logger.debug("%s 성공 (%.0fms, 시도 %d)", name, elapsed_ms, attempt)
                if cache_key is not None and cache_ttl is not None:
                    # 성공만 저장한다. 실패를 캐시하면 업스트림이 살아난 뒤에도
                    # TTL이 끝날 때까지 우리 쪽에서 장애를 연장하게 된다
                    await cache.set_json(cache_key, payload, cache_ttl)
                return payload

            if last_status not in _RETRYABLE_STATUS:
                logger.error("%s 실패 — 재시도하지 않는다 (status=%d)", name, last_status)
                raise UpstreamUnavailable(name, last_status)

            logger.warning(
                "%s 응답 오류 (status=%d, 시도 %d/%d)",
                name,
                last_status,
                attempt,
                _MAX_ATTEMPTS,
            )

        if attempt < _MAX_ATTEMPTS:
            await asyncio.sleep(
                _BACKOFF_SECONDS[attempt - 1] + random.uniform(0, _JITTER_SECONDS)
            )

    elapsed_ms = (time.perf_counter() - started) * 1000
    logger.error("%s 최종 실패 (%.0fms, %d회 시도)", name, elapsed_ms, _MAX_ATTEMPTS)
    raise UpstreamUnavailable(name, last_status)


async def aclose() -> None:
    """lifespan 종료용. 다음 호출이 새 클라이언트를 만들도록 전역도 비운다."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
