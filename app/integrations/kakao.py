"""카카오 로컬 — 장소 검색. 이 층의 실패는 치명적이다.

`blocks.place_id`는 NOT NULL이고 빈 문자열도 금지다(ADR-0009의 환각 차단 계약). 그 값을
만들 수 있는 곳이 여기뿐이라, 카카오가 죽으면 일정을 만들 수 없다 — 예외를 그대로 올린다.
날씨(`weather.py`)와 정확히 반대다 (ADR-0010).
"""

import hashlib
import logging
from typing import Any

from pydantic import BaseModel

from app.config import settings
from app.integrations import http

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"

# 장소는 자주 안 바뀌고, 한 번의 계획 세션에서 같은 질의가 여러 번 나온다.
# 영업정보의 최신성은 이 TTL이 아니라 Phase 5의 D-1 재검증이 책임진다
_CACHE_TTL_SECONDS = 60 * 60 * 24
# 키에 박힌 버전. 아래 파싱이 바뀌면 v2로 올려서 옛 모양의 캐시를 자연 만료시킨다 —
# 배포 후 FLUSHDB를 손으로 하는 것보다 안전하다
_CACHE_VERSION = "v1"

# 카카오 문서상 size 상한. 넘겨 보내면 400이 온다
MAX_SIZE = 15


class KakaoNotConfigured(RuntimeError):
    """REST 키가 비었다. 네트워크를 타기 전에 즉시 실패한다."""


class PlaceCandidate(BaseModel):
    """검색 결과 한 건. 필드 이름을 `blocks`의 컬럼에 맞춰 두었다.

    세션 12~14의 graph가 이걸 블록으로 옮길 때 이름 대응표를 따로 들고 다니지 않게 된다.
    address·phone·url은 아직 컬럼이 없다 — ROADMAP 백로그가 "카카오 응답을 실제로 본 뒤"로
    미뤄 둔 항목이라, 여기까지만 실어 나르고 저장은 하지 않는다.
    """

    place_id: str
    place_name: str
    place_category: str | None = None
    latitude: float
    longitude: float
    address: str | None = None
    phone: str | None = None
    url: str | None = None


def _blank_to_none(value: str | None) -> str | None:
    """카카오는 값이 없을 때 null이 아니라 빈 문자열을 준다.

    그대로 두면 `place_category=""`가 저장되어 "분류를 모른다"와 "분류가 빈 문자열이다"가
    섞인다. Phase 2의 Plan B가 같은 카테고리를 찾을 때 그 둘은 다르게 다뤄져야 한다.
    """
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _to_candidate(doc: dict[str, Any]) -> PlaceCandidate:
    """카카오 문서 한 건 → 우리 계약.

    **x가 경도(longitude), y가 위도(latitude)이고 둘 다 문자열이다.** 뒤집어도 타입 에러가
    나지 않고, 지도에 아프리카 앞바다가 찍힐 뿐이다. 이 프로젝트에서 가장 조용히 틀릴 수
    있는 줄이라 테스트로 고정해 두었다.
    """
    # 큰 분류(음식점·카페·관광명소)가 있으면 그걸 쓴다. Plan B가 "같은 카테고리"를 찾을 때
    # 필요한 건 "가정,생활 > 문구,사무용품 > ..." 전체 경로가 아니라 이 한 단어다.
    # 분류 코드가 없는 장소는 group_name이 비어 오므로 전체 경로의 마지막 조각으로 내려간다
    category = _blank_to_none(doc.get("category_group_name"))
    if category is None:
        full_path = _blank_to_none(doc.get("category_name"))
        if full_path is not None:
            category = full_path.split(">")[-1].strip() or None

    return PlaceCandidate(
        place_id=str(doc["id"]),
        place_name=doc["place_name"],
        place_category=category,
        longitude=float(doc["x"]),
        latitude=float(doc["y"]),
        # 도로명이 더 정확하지만 없는 장소가 있다. 지번으로 내려간다
        address=_blank_to_none(doc.get("road_address_name"))
        or _blank_to_none(doc.get("address_name")),
        phone=_blank_to_none(doc.get("phone")),
        url=_blank_to_none(doc.get("place_url")),
    )


def _cache_key(
    query: str, latitude: float | None, longitude: float | None, radius_m: int | None, size: int
) -> str:
    """질의를 그대로 키에 넣지 않는다 — 한글·공백·콜론이 키 규약을 흔든다."""
    raw = f"{query}|{latitude}|{longitude}|{radius_m}|{size}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"kakao:search:{_CACHE_VERSION}:{digest}"


async def search_places(
    query: str,
    *,
    latitude: float | None = None,
    longitude: float | None = None,
    radius_m: int | None = None,
    size: int = 5,
) -> list[PlaceCandidate]:
    """키워드로 장소를 찾는다. 실패하면 예외가 그대로 올라간다.

    좌표를 주면 그 주변으로 좁힌다. 카카오는 radius를 x·y 없이 받지 않으므로,
    좌표 없이 radius만 준 호출은 요청을 만들기 전에 여기서 거른다.
    """
    if not settings.kakao_rest_api_key:
        raise KakaoNotConfigured(
            "KAKAO_REST_API_KEY가 비어 있다. .env에 REST API 키를 넣어야 장소 검색이 된다"
        )

    size = min(size, MAX_SIZE)
    params: dict[str, Any] = {"query": query, "size": size}
    if latitude is not None and longitude is not None:
        params["x"] = longitude
        params["y"] = latitude
        if radius_m is not None:
            params["radius"] = radius_m
    elif radius_m is not None:
        raise ValueError("radius_m은 좌표(latitude·longitude)와 함께만 쓸 수 있다")

    payload = await http.fetch_json(
        name="kakao.search",
        url=_SEARCH_URL,
        params=params,
        # 키는 헤더로 간다. 쿼리스트링에 실리지 않으므로 URL이 어딘가에 남아도 새지 않는다
        headers={"Authorization": f"KakaoAK {settings.kakao_rest_api_key}"},
        cache_key=_cache_key(query, latitude, longitude, radius_m, size),
        cache_ttl=_CACHE_TTL_SECONDS,
    )

    candidates = [_to_candidate(doc) for doc in payload["documents"]]
    logger.debug("kakao.search 결과 %d건 (query=%s)", len(candidates), query)
    return candidates
