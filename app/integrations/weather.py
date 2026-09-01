"""Open-Meteo — 일별 예보. 이 층의 실패는 무시된다.

**`None`은 "모른다"는 뜻이고, 그건 정상 응답이다.** 날씨는 일정을 더 좋게 만드는 재료이지
일정의 존재 조건이 아니다 — 여기서 예외가 새면 날씨 API 하나가 서비스 전체를 멈춘다.
장소(`kakao.py`)와 정확히 반대다 (ADR-0010).

키가 필요 없는 API다. 그래서 CI도, 이 리포를 처음 받은 사람도 그냥 돌려볼 수 있다.
"""

import logging
from datetime import UTC, date, datetime, timedelta

from pydantic import BaseModel

from app.integrations import http

logger = logging.getLogger(__name__)

_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# Open-Meteo가 내주는 예보 상한. 석 달 뒤 여행은 예보가 존재하지 않는다 —
# 그건 장애가 아니라 정상이므로, 안 될 걸 알면서 부르지 않는다.
# 여행이 임박하면 Phase 5의 감시가 다시 본다
FORECAST_HORIZON_DAYS = 16

# 예보는 한 시간 단위로 갱신된다. 더 길게 잡으면 "감시"라면서 옛 값을 보게 된다
_CACHE_TTL_SECONDS = 60 * 60
_CACHE_VERSION = "v1"

# 좌표를 소수 2자리(약 1.1km)로 반올림한다. 이 한 줄이 이 캐시의 존재 이유다 —
# 블록마다 좌표가 미세하게 다른데 그대로 키에 넣으면 적중률이 구조적으로 0이 된다.
# 예보 모델의 격자 자체가 10km 단위라 1.1km 반올림으로 잃는 정보도 없다
_COORD_PRECISION = 2

_DAILY_FIELDS = (
    "temperature_2m_max",
    "temperature_2m_min",
    "precipitation_probability_max",
    "precipitation_sum",
    "weather_code",
)


class DailyWeather(BaseModel):
    """하루치 예보. 값이 없는 항목은 None으로 온다 — 없는 걸 0으로 채우면 조용히 틀린다."""

    date: date
    temp_min_c: float | None = None
    temp_max_c: float | None = None
    precip_prob_pct: int | None = None
    precip_mm: float | None = None
    # WMO 코드. 0=맑음, 61~65=비, 71~75=눈. 사람이 읽을 문구로 바꾸는 것은 이 층의 일이 아니다
    weather_code: int | None = None


def _cache_key(latitude: float, longitude: float, start: date, end: date) -> str:
    return (
        f"weather:daily:{_CACHE_VERSION}:"
        f"{latitude:.{_COORD_PRECISION}f},{longitude:.{_COORD_PRECISION}f}:{start}:{end}"
    )


def _to_daily(payload: dict) -> list[DailyWeather]:
    """Open-Meteo는 행이 아니라 열로 준다 — 같은 길이의 배열 여러 개를 지퍼처럼 묶는다."""
    daily = payload["daily"]
    times = daily["time"]

    def column(name: str) -> list:
        # 요청한 항목이 통째로 빠져 오는 경우가 있다. 길이를 맞춰 None으로 채운다
        return daily.get(name) or [None] * len(times)

    return [
        DailyWeather(
            date=date.fromisoformat(day),
            temp_max_c=column("temperature_2m_max")[i],
            temp_min_c=column("temperature_2m_min")[i],
            precip_prob_pct=column("precipitation_probability_max")[i],
            precip_mm=column("precipitation_sum")[i],
            weather_code=column("weather_code")[i],
        )
        for i, day in enumerate(times)
    ]


async def get_daily_forecast(
    latitude: float, longitude: float, start: date, end: date
) -> list[DailyWeather] | None:
    """예보를 가져온다. 모르면 None — 호출자는 None을 정상 분기로 다룬다.

    예보 범위를 넘는 뒷부분은 잘라내고 앞부분만 돌려준다. 4일 중 2일이라도 아는 것이
    통째로 모르는 것보다 낫다.
    """
    if end < start:
        raise ValueError("end는 start보다 앞설 수 없다")

    # 서버는 UTC, 개발 노트북은 KST다. 16일 지평선에서 하루 차이는 의미가 없고,
    # 경계에서 어긋나면 업스트림이 400을 주고 우리는 None으로 흡수한다
    horizon = datetime.now(UTC).date() + timedelta(days=FORECAST_HORIZON_DAYS)
    if start > horizon:
        logger.debug("예보 범위 밖이라 호출하지 않는다 (start=%s, horizon=%s)", start, horizon)
        return None
    end = min(end, horizon)

    # 키에 쓴 좌표와 실제로 물어본 좌표가 같아야 한다. 반올림 전 좌표로 물으면
    # 캐시에 든 값이 키가 가리키는 지점의 값이 아니게 된다
    latitude = round(latitude, _COORD_PRECISION)
    longitude = round(longitude, _COORD_PRECISION)

    try:
        payload = await http.fetch_json(
            name="weather.daily",
            url=_FORECAST_URL,
            params={
                "latitude": latitude,
                "longitude": longitude,
                "daily": ",".join(_DAILY_FIELDS),
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                # 좌표에서 현지 시간대를 추론한다. 날짜 경계가 현지 자정이어야
                # "2일차 비"가 실제 2일차와 맞는다
                "timezone": "auto",
            },
            cache_key=_cache_key(latitude, longitude, start, end),
            cache_ttl=_CACHE_TTL_SECONDS,
        )
        return _to_daily(payload)
    except http.UpstreamUnavailable:
        logger.warning("날씨를 못 받았다 — 날씨 없이 진행한다 (%s~%s)", start, end)
        return None
    except Exception:
        # 여기서만 Exception을 넓게 잡는다. 응답 모양이 바뀌어 파싱이 깨지는 것은
        # 업스트림 변경이지 우리 요청의 문제가 아닌데, 그 하나가 새벽에 계획 생성을
        # 통째로 멈추면 안 된다(운영 인력 0명 — R3). 대신 error로 크게 남긴다
        logger.exception("날씨 응답을 해석하지 못했다 — 날씨 없이 진행한다")
        return None
