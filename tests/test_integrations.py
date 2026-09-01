"""외부 API 층. 붙잡는 계약은 넷이다 — 좌표를 뒤집지 않는 것, 재시도할 것만 재시도하는 것,
같은 질문을 두 번 사 오지 않는 것, 그리고 **날씨가 죽어도 일정은 나오는 것**.

네 번째가 이 세션의 주제다. 그래서 kakao와 weather를 같은 파일에서 본다 — 장애 격리는
"모든 외부 호출을 똑같이 감싼다"가 아니라 **둘을 다르게 다룬다**는 결정이고,
그 결정은 나란히 놓아야만 보인다 (ADR-0010).

바깥 네트워크를 타지 않는다. httpx.MockTransport를 전송 계층에 끼우므로 재시도·타임아웃·
파싱·캐시라는 진짜 코드 경로는 그대로 돈다 — 가짜인 것은 응답뿐이다.
"""

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest

from app.config import settings
from app.integrations import http, kakao, weather

KAKAO_DOC = {
    "id": "26338954",
    "place_name": "돼지국밥집",
    "category_name": "음식점 > 한식 > 국밥",
    "category_group_code": "FD6",
    "category_group_name": "음식점",
    "phone": "051-000-0000",
    "address_name": "부산 중구 남포동 1",
    "road_address_name": "부산 중구 광복로 1",
    # x가 경도, y가 위도, 둘 다 문자열이다
    "x": "129.0325",
    "y": "35.0979",
    "place_url": "http://place.map.kakao.com/26338954",
}
KAKAO_OK = {"documents": [KAKAO_DOC], "meta": {"total_count": 1, "is_end": True}}

WEATHER_OK = {
    "daily": {
        "time": ["2026-09-10", "2026-09-11"],
        "temperature_2m_max": [29.4, 26.1],
        "temperature_2m_min": [23.0, 21.8],
        "precipitation_probability_max": [10, 80],
        "precipitation_sum": [0.0, 14.2],
        "weather_code": [1, 61],
    }
}

BUSAN = (35.0979, 129.0325)


def install(monkeypatch: pytest.MonkeyPatch, handler: Callable) -> list[httpx.Request]:
    """전역 클라이언트를 MockTransport로 갈아끼우고, 오간 요청을 기록해 돌려준다.

    반환된 리스트의 길이가 곧 "네트워크를 몇 번 탔는가"다 — 재시도 횟수와 캐시 적중을
    이 숫자 하나로 판정한다.
    """
    calls: list[httpx.Request] = []

    def recording(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return handler(request)

    monkeypatch.setattr(
        http, "_client", httpx.AsyncClient(transport=httpx.MockTransport(recording))
    )
    return calls


def responds(*responses: httpx.Response | Exception) -> Callable:
    """호출 순서대로 정해진 응답을 낸다. 다 쓰면 마지막 것을 반복한다."""
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return item

    return handler


@pytest.fixture(autouse=True)
def fast_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """백오프를 0으로 만든다.

    이 파일이 붙잡는 것은 "무엇을 몇 번 재시도하는가"이지 "얼마나 기다리는가"가 아니다.
    대기 시간까지 실시간으로 재면 테스트가 느려지기만 한다.
    """
    monkeypatch.setattr(http, "_BACKOFF_SECONDS", (0, 0))
    monkeypatch.setattr(http, "_JITTER_SECONDS", 0)


@pytest.fixture
def kakao_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "kakao_rest_api_key", "test_key_not_a_secret")


def today() -> date:
    return datetime.now(UTC).date()


# 장소 계약 ---


async def test_kakao_reads_x_as_longitude_and_y_as_latitude(
    monkeypatch: pytest.MonkeyPatch, kakao_key: None, redis_cache: None
) -> None:
    """이 프로젝트에서 가장 조용히 틀릴 수 있는 줄.

    뒤집어도 타입 에러가 나지 않는다 — 지도에 아프리카 앞바다가 찍힐 뿐이다.
    """
    install(monkeypatch, responds(httpx.Response(200, json=KAKAO_OK)))

    [place] = await kakao.search_places("부산 돼지국밥")

    assert place.longitude == 129.0325
    assert place.latitude == 35.0979
    assert place.place_id == "26338954"
    assert place.place_category == "음식점"


async def test_kakao_falls_back_to_the_category_path_when_the_group_is_blank(
    monkeypatch: pytest.MonkeyPatch, kakao_key: None, redis_cache: None
) -> None:
    """분류 코드가 없는 장소는 group_name이 빈 문자열로 온다."""
    doc = KAKAO_DOC | {"category_group_name": "", "category_name": "여행 > 관광,명소 > 전망대"}
    install(monkeypatch, responds(httpx.Response(200, json={"documents": [doc]})))

    [place] = await kakao.search_places("전망대")

    assert place.place_category == "전망대"


async def test_kakao_turns_blank_strings_into_none(
    monkeypatch: pytest.MonkeyPatch, kakao_key: None, redis_cache: None
) -> None:
    """카카오는 값이 없을 때 null이 아니라 ""를 준다. 둘을 섞으면 Phase 2가 헛돈다."""
    doc = KAKAO_DOC | {"phone": "", "road_address_name": "", "address_name": ""}
    install(monkeypatch, responds(httpx.Response(200, json={"documents": [doc]})))

    [place] = await kakao.search_places("이름없는곳")

    assert place.phone is None
    assert place.address is None


async def test_kakao_without_a_key_fails_before_the_network(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    """키가 없으면 네트워크를 타지 않는다. 헛되이 3번 재시도할 이유가 없다."""
    monkeypatch.setattr(settings, "kakao_rest_api_key", "")
    calls = install(monkeypatch, responds(httpx.Response(200, json=KAKAO_OK)))

    with pytest.raises(kakao.KakaoNotConfigured):
        await kakao.search_places("부산 돼지국밥")

    assert calls == []


async def test_kakao_rejects_a_radius_without_coordinates(
    monkeypatch: pytest.MonkeyPatch, kakao_key: None
) -> None:
    """카카오는 x·y 없이 radius를 받지 않는다. 400을 사 오지 말고 여기서 막는다."""
    calls = install(monkeypatch, responds(httpx.Response(200, json=KAKAO_OK)))

    with pytest.raises(ValueError):
        await kakao.search_places("국밥", radius_m=500)

    assert calls == []


# 재시도 ---


async def test_a_server_error_is_retried_and_can_succeed(
    monkeypatch: pytest.MonkeyPatch, kakao_key: None, redis_cache: None
) -> None:
    calls = install(
        monkeypatch,
        responds(httpx.Response(503), httpx.Response(200, json=KAKAO_OK)),
    )

    [place] = await kakao.search_places("부산 돼지국밥")

    assert place.place_name == "돼지국밥집"
    assert len(calls) == 2


async def test_three_server_errors_give_up(
    monkeypatch: pytest.MonkeyPatch, kakao_key: None, redis_cache: None
) -> None:
    """상한이 없으면 죽은 업스트림에 매달려 사용자를 무한정 기다리게 한다."""
    calls = install(monkeypatch, responds(httpx.Response(500)))

    with pytest.raises(http.UpstreamUnavailable) as exc:
        await kakao.search_places("부산 돼지국밥")

    assert len(calls) == 3
    assert exc.value.status_code == 500


async def test_a_client_error_is_not_retried(
    monkeypatch: pytest.MonkeyPatch, kakao_key: None, redis_cache: None
) -> None:
    """401·400은 다시 물어도 같은 답이다. 재시도하면 대기시간만 3배가 된다."""
    calls = install(monkeypatch, responds(httpx.Response(401)))

    with pytest.raises(http.UpstreamUnavailable) as exc:
        await kakao.search_places("부산 돼지국밥")

    assert len(calls) == 1
    assert exc.value.status_code == 401


async def test_a_timeout_is_retried(
    monkeypatch: pytest.MonkeyPatch, kakao_key: None, redis_cache: None
) -> None:
    """붙지도 못한 경우다. 상태코드가 없으므로 None으로 남는다."""
    calls = install(monkeypatch, responds(httpx.ConnectTimeout("느리다")))

    with pytest.raises(http.UpstreamUnavailable) as exc:
        await kakao.search_places("부산 돼지국밥")

    assert len(calls) == 3
    assert exc.value.status_code is None


# 캐시 ---


async def test_a_repeated_search_does_not_touch_the_network(
    monkeypatch: pytest.MonkeyPatch, kakao_key: None, redis_cache: None
) -> None:
    """한 번의 계획 세션에서 같은 질의가 여러 번 나온다. 두 번 사 오면 그만큼 돈이다."""
    calls = install(monkeypatch, responds(httpx.Response(200, json=KAKAO_OK)))

    first = await kakao.search_places("부산 돼지국밥")
    second = await kakao.search_places("부산 돼지국밥")

    assert first == second
    assert len(calls) == 1


async def test_a_failure_is_not_cached(
    monkeypatch: pytest.MonkeyPatch, kakao_key: None, redis_cache: None
) -> None:
    """실패를 캐시하면 업스트림이 살아난 뒤에도 TTL이 끝날 때까지 우리가 장애를 연장한다."""
    install(monkeypatch, responds(httpx.Response(500)))
    with pytest.raises(http.UpstreamUnavailable):
        await kakao.search_places("부산 돼지국밥")

    calls = install(monkeypatch, responds(httpx.Response(200, json=KAKAO_OK)))
    [place] = await kakao.search_places("부산 돼지국밥")

    assert place.place_name == "돼지국밥집"
    assert len(calls) == 1


async def test_nearby_coordinates_share_one_cache_entry(
    monkeypatch: pytest.MonkeyPatch, redis_cache: None
) -> None:
    """반올림이 없으면 블록마다 좌표가 달라 적중률이 구조적으로 0이 된다."""
    calls = install(monkeypatch, responds(httpx.Response(200, json=WEATHER_OK)))
    start = today()
    end = start + timedelta(days=1)

    await weather.get_daily_forecast(35.0979, 129.0325, start, end)
    # 소수 셋째 자리만 다르다 — 약 100m 떨어진 옆 블록
    await weather.get_daily_forecast(35.0983, 129.0321, start, end)

    assert len(calls) == 1


# 장애 격리 ---


async def test_weather_returns_none_when_upstream_is_down(
    monkeypatch: pytest.MonkeyPatch, redis_cache: None
) -> None:
    """이 세션의 주제. 예외가 아니라 None이고, None은 정상 응답이다."""
    install(monkeypatch, responds(httpx.Response(503)))

    result = await weather.get_daily_forecast(*BUSAN, today(), today() + timedelta(days=1))

    assert result is None


async def test_weather_returns_none_on_a_timeout(
    monkeypatch: pytest.MonkeyPatch, redis_cache: None
) -> None:
    install(monkeypatch, responds(httpx.ReadTimeout("느리다")))

    result = await weather.get_daily_forecast(*BUSAN, today(), today() + timedelta(days=1))

    assert result is None


async def test_weather_returns_none_when_the_response_shape_changes(
    monkeypatch: pytest.MonkeyPatch, redis_cache: None
) -> None:
    """업스트림이 모양을 바꾸는 것은 우리 요청의 문제가 아니다.

    그 하나가 새벽에 계획 생성을 통째로 멈추면 안 된다 — 운영 인력이 0명이다 (R3).
    """
    install(monkeypatch, responds(httpx.Response(200, json={"뜬금없는": "모양"})))

    result = await weather.get_daily_forecast(*BUSAN, today(), today() + timedelta(days=1))

    assert result is None


async def test_weather_beyond_the_horizon_is_not_requested(
    monkeypatch: pytest.MonkeyPatch, redis_cache: None
) -> None:
    """석 달 뒤 여행은 예보가 존재하지 않는다. 안 될 걸 알면서 부르지 않는다."""
    calls = install(monkeypatch, responds(httpx.Response(200, json=WEATHER_OK)))
    far = today() + timedelta(days=90)

    result = await weather.get_daily_forecast(*BUSAN, far, far + timedelta(days=3))

    assert result is None
    assert calls == []


async def test_weather_clamps_the_end_date_to_the_horizon(
    monkeypatch: pytest.MonkeyPatch, redis_cache: None
) -> None:
    """4일 중 2일이라도 아는 것이 통째로 모르는 것보다 낫다."""
    calls = install(monkeypatch, responds(httpx.Response(200, json=WEATHER_OK)))
    horizon = today() + timedelta(days=weather.FORECAST_HORIZON_DAYS)

    await weather.get_daily_forecast(*BUSAN, today(), today() + timedelta(days=60))

    assert calls[0].url.params["end_date"] == horizon.isoformat()


async def test_weather_parses_a_column_shaped_response(
    monkeypatch: pytest.MonkeyPatch, redis_cache: None
) -> None:
    """Open-Meteo는 행이 아니라 열로 준다 — 같은 길이의 배열 여러 개를 묶어야 한다."""
    install(monkeypatch, responds(httpx.Response(200, json=WEATHER_OK)))

    days = await weather.get_daily_forecast(*BUSAN, today(), today() + timedelta(days=1))

    assert [d.date.isoformat() for d in days] == ["2026-09-10", "2026-09-11"]
    assert days[1].precip_prob_pct == 80
    assert days[1].weather_code == 61


async def test_a_dead_upstream_is_fatal_for_places_but_not_for_weather(
    monkeypatch: pytest.MonkeyPatch, kakao_key: None, redis_cache: None
) -> None:
    """이 세션의 결정을 한 화면에 놓는다.

    place_id 없이는 블록이 존재할 수 없고(ADR-0009), 날씨 없이는 존재할 수 있다.
    같은 장애에 다르게 반응하는 것이 "장애 격리"의 실체다.
    """
    install(monkeypatch, responds(httpx.Response(503)))

    assert await weather.get_daily_forecast(*BUSAN, today(), today()) is None

    with pytest.raises(http.UpstreamUnavailable):
        await kakao.search_places("부산 돼지국밥")
