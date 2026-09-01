"""여행의 내용물. 붙잡는 계약은 셋이다 — 일정으로서 정렬되어 나오는 것,
place_id 없는 블록은 존재할 수 없는 것, 그리고 남의 일정이 안 보이는 것.
"""

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.trips.models import Block

PASSWORD = "test-password-1234"
TRIP = {
    "title": "오사카 미식",
    "destination": "오사카",
    "start_date": "2026-10-01",
    "end_date": "2026-10-04",
    "budget_total": 1_500_000,
}
BLOCK = {
    "day_index": 1,
    "start_time": "09:00:00",
    "duration_min": 90,
    "place_id": "kakao:26338954",
    "place_name": "구로몬 시장",
    "place_category": "음식점",
    "latitude": 34.665442,
    "longitude": 135.506302,
    "priority": "anchor",
    "booking": "none",
    "cost": 20_000,
}


async def auth_headers(client: AsyncClient, email: str) -> dict[str, str]:
    """가입 → 로그인 → Authorization 헤더. 소유권 테스트는 계정이 둘 필요하다."""
    await client.post("/auth/signup", json={"email": email, "password": PASSWORD})
    token = (
        await client.post("/auth/login", data={"username": email, "password": PASSWORD})
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


async def create_trip(client: AsyncClient, headers: dict[str, str]) -> int:
    return (await client.post("/trips", json=TRIP, headers=headers)).json()["id"]


async def put_blocks(
    client: AsyncClient, headers: dict[str, str], trip_id: int, *blocks: dict
):
    return await client.put(
        f"/trips/{trip_id}/blocks", json=list(blocks), headers=headers
    )


# 환각 차단과 값 계약 --------------------------------------------------


async def test_block_without_place_id_returns_422(client: AsyncClient) -> None:
    """place_id가 이 프로젝트의 실존 증명이다. 없는 블록은 만들어질 수 없다."""
    headers = await auth_headers(client, "owner@example.com")
    trip_id = await create_trip(client, headers)
    without = {k: v for k, v in BLOCK.items() if k != "place_id"}

    response = await put_blocks(client, headers, trip_id, without)

    assert response.status_code == 422


async def test_block_with_blank_place_id_returns_422(client: AsyncClient) -> None:
    headers = await auth_headers(client, "owner@example.com")
    trip_id = await create_trip(client, headers)

    response = await put_blocks(client, headers, trip_id, BLOCK | {"place_id": ""})

    assert response.status_code == 422


async def test_unknown_priority_returns_422(client: AsyncClient) -> None:
    headers = await auth_headers(client, "owner@example.com")
    trip_id = await create_trip(client, headers)

    response = await put_blocks(client, headers, trip_id, BLOCK | {"priority": "maybe"})

    assert response.status_code == 422


async def test_zero_duration_returns_422(client: AsyncClient) -> None:
    headers = await auth_headers(client, "owner@example.com")
    trip_id = await create_trip(client, headers)

    response = await put_blocks(client, headers, trip_id, BLOCK | {"duration_min": 0})

    assert response.status_code == 422


async def test_negative_numbers_return_422(client: AsyncClient) -> None:
    headers = await auth_headers(client, "owner@example.com")
    trip_id = await create_trip(client, headers)

    for field in ("slack_min", "cost", "day_index"):
        response = await put_blocks(client, headers, trip_id, BLOCK | {field: -1})

        assert response.status_code == 422, field


async def test_confirming_a_booking_that_is_not_required_returns_422(
    client: AsyncClient,
) -> None:
    """예약이 필요 없는데 확정했다는 블록은 상태가 아니라 모순이다."""
    headers = await auth_headers(client, "owner@example.com")
    trip_id = await create_trip(client, headers)

    response = await put_blocks(
        client, headers, trip_id, BLOCK | {"booking": "none", "booking_confirmed": True}
    )

    assert response.status_code == 422


async def test_half_a_coordinate_returns_422(client: AsyncClient) -> None:
    """반쪽 좌표로는 도보권 판정도 이동시간 계산도 못 한다."""
    headers = await auth_headers(client, "owner@example.com")
    trip_id = await create_trip(client, headers)

    response = await put_blocks(client, headers, trip_id, BLOCK | {"longitude": None})

    assert response.status_code == 422


async def test_more_than_two_alternates_returns_422(client: AsyncClient) -> None:
    headers = await auth_headers(client, "owner@example.com")
    trip_id = await create_trip(client, headers)
    three = [{"place_id": f"p{i}", "place_name": f"대안 {i}"} for i in range(3)]

    response = await put_blocks(client, headers, trip_id, BLOCK | {"alternates": three})

    assert response.status_code == 422


# 일정으로서의 행위 ----------------------------------------------------


async def test_put_returns_the_stored_plan(client: AsyncClient) -> None:
    headers = await auth_headers(client, "owner@example.com")
    trip_id = await create_trip(client, headers)

    response = await put_blocks(client, headers, trip_id, BLOCK)

    assert response.status_code == 200
    (block,) = response.json()
    assert block["place_id"] == BLOCK["place_id"]
    assert block["priority"] == "anchor"
    assert block["cost"] == 20_000
    assert block["latitude"] == BLOCK["latitude"]
    # 소유 관계는 URL이 말한다 — TripRead가 user_id를 뺀 것과 같은 이유
    assert "trip_id" not in block


async def test_end_time_is_computed_and_wraps_past_midnight(client: AsyncClient) -> None:
    """길이를 저장하고 끝 시각은 계산한다. 그래서 23시 시작 2시간짜리가 존재할 수 있다."""
    headers = await auth_headers(client, "owner@example.com")
    trip_id = await create_trip(client, headers)

    response = await put_blocks(
        client, headers, trip_id, BLOCK | {"start_time": "23:00:00", "duration_min": 120}
    )

    assert response.json()[0]["end_time"] == "01:00:00"


async def test_get_returns_blocks_in_day_and_time_order(client: AsyncClient) -> None:
    """넣은 순서가 아니라 일정 순서로 나온다."""
    headers = await auth_headers(client, "owner@example.com")
    trip_id = await create_trip(client, headers)
    await put_blocks(
        client,
        headers,
        trip_id,
        BLOCK | {"day_index": 2, "start_time": "09:00:00", "place_name": "둘째날 아침"},
        BLOCK | {"day_index": 1, "start_time": "14:00:00", "place_name": "첫날 오후"},
        BLOCK | {"day_index": 1, "start_time": "09:00:00", "place_name": "첫날 아침"},
    )

    response = await client.get(f"/trips/{trip_id}/blocks", headers=headers)

    assert response.status_code == 200
    names = [block["place_name"] for block in response.json()]
    assert names == ["첫날 아침", "첫날 오후", "둘째날 아침"]


async def test_put_replaces_the_previous_plan(client: AsyncClient) -> None:
    """전량 교체다. 덧붙이기가 아니라는 것이 이 API의 정체성이다."""
    headers = await auth_headers(client, "owner@example.com")
    trip_id = await create_trip(client, headers)
    await put_blocks(
        client,
        headers,
        trip_id,
        BLOCK | {"start_time": "09:00:00"},
        BLOCK | {"start_time": "12:00:00"},
        BLOCK | {"start_time": "15:00:00"},
    )

    await put_blocks(client, headers, trip_id, BLOCK | {"place_name": "새 계획"})

    remaining = (await client.get(f"/trips/{trip_id}/blocks", headers=headers)).json()
    assert [block["place_name"] for block in remaining] == ["새 계획"]


async def test_put_empty_list_clears_the_plan(client: AsyncClient) -> None:
    """일정이 없는 여행은 404가 아니라 빈 일정이다."""
    headers = await auth_headers(client, "owner@example.com")
    trip_id = await create_trip(client, headers)
    await put_blocks(client, headers, trip_id, BLOCK)

    response = await put_blocks(client, headers, trip_id)

    assert response.status_code == 200
    assert response.json() == []
    assert (await client.get(f"/trips/{trip_id}/blocks", headers=headers)).json() == []


async def test_overlapping_blocks_on_the_same_day_return_422(
    client: AsyncClient,
) -> None:
    """한 사람이 두 곳에 동시에 있을 수는 없다."""
    headers = await auth_headers(client, "owner@example.com")
    trip_id = await create_trip(client, headers)

    response = await put_blocks(
        client,
        headers,
        trip_id,
        BLOCK | {"start_time": "09:00:00", "duration_min": 90},
        BLOCK | {"start_time": "10:00:00", "duration_min": 60},
    )

    assert response.status_code == 422


async def test_touching_blocks_are_allowed(client: AsyncClient) -> None:
    """끝나는 시각과 시작하는 시각이 같은 것은 겹침이 아니다 — 경계를 확인한다."""
    headers = await auth_headers(client, "owner@example.com")
    trip_id = await create_trip(client, headers)

    response = await put_blocks(
        client,
        headers,
        trip_id,
        BLOCK | {"start_time": "09:00:00", "duration_min": 60},
        BLOCK | {"start_time": "10:00:00", "duration_min": 60},
    )

    assert response.status_code == 200


async def test_same_time_on_different_days_is_allowed(client: AsyncClient) -> None:
    """겹침 검사가 하루 안에서만 도는지 — 과하게 넓으면 정상 일정이 막힌다."""
    headers = await auth_headers(client, "owner@example.com")
    trip_id = await create_trip(client, headers)

    response = await put_blocks(
        client,
        headers,
        trip_id,
        BLOCK | {"day_index": 1, "start_time": "09:00:00"},
        BLOCK | {"day_index": 2, "start_time": "09:00:00"},
    )

    assert response.status_code == 200
    assert len(response.json()) == 2


async def test_alternates_survive_the_json_round_trip(client: AsyncClient) -> None:
    """Plan B는 사전 계산된 스냅샷이다. 순서와 좌표가 그대로 돌아와야 한다."""
    headers = await auth_headers(client, "owner@example.com")
    trip_id = await create_trip(client, headers)
    alternates = [
        {"place_id": "kakao:1", "place_name": "대안 하나", "place_category": "음식점"},
        {
            "place_id": "kakao:2",
            "place_name": "대안 둘",
            "latitude": 34.1,
            "longitude": 135.2,
        },
    ]

    await put_blocks(client, headers, trip_id, BLOCK | {"alternates": alternates})

    (block,) = (await client.get(f"/trips/{trip_id}/blocks", headers=headers)).json()
    assert [alt["place_name"] for alt in block["alternates"]] == ["대안 하나", "대안 둘"]
    assert block["alternates"][1]["latitude"] == 34.1


async def test_verified_at_starts_as_null(client: AsyncClient) -> None:
    """아직 아무도 영업정보를 확인하지 않았다. NULL이 그 사실이다."""
    headers = await auth_headers(client, "owner@example.com")
    trip_id = await create_trip(client, headers)

    response = await put_blocks(client, headers, trip_id, BLOCK)

    assert response.json()[0]["verified_at"] is None


# 인가 ----------------------------------------------------------------


async def test_blocks_without_token_return_401(client: AsyncClient) -> None:
    headers = await auth_headers(client, "owner@example.com")
    trip_id = await create_trip(client, headers)

    read = await client.get(f"/trips/{trip_id}/blocks")
    write = await client.put(f"/trips/{trip_id}/blocks", json=[BLOCK])

    assert read.status_code == write.status_code == 401


async def test_others_blocks_are_indistinguishable_from_a_missing_trip(
    client: AsyncClient,
) -> None:
    """일정 라우트도 여행 라우트와 글자까지 같은 404여야 한다 — 갈라지면 존재가 샌다."""
    owner = await auth_headers(client, "owner@example.com")
    stranger = await auth_headers(client, "stranger@example.com")
    trip_id = await create_trip(client, owner)
    await put_blocks(client, owner, trip_id, BLOCK)

    others = await client.get(f"/trips/{trip_id}/blocks", headers=stranger)
    missing = await client.get("/trips/999999/blocks", headers=stranger)
    missing_trip = await client.get("/trips/999999", headers=stranger)

    assert others.status_code == missing.status_code == 404
    assert others.json() == missing.json() == missing_trip.json()


async def test_others_plan_cannot_be_replaced(client: AsyncClient) -> None:
    owner = await auth_headers(client, "owner@example.com")
    stranger = await auth_headers(client, "stranger@example.com")
    trip_id = await create_trip(client, owner)
    await put_blocks(client, owner, trip_id, BLOCK)

    response = await put_blocks(
        client, stranger, trip_id, BLOCK | {"place_name": "가로채기"}
    )

    assert response.status_code == 404
    # 정말로 안 바뀌었는지는 주인 눈으로 확인한다
    (block,) = (await client.get(f"/trips/{trip_id}/blocks", headers=owner)).json()
    assert block["place_name"] == BLOCK["place_name"]


# 관계 ----------------------------------------------------------------


async def test_deleting_a_trip_deletes_its_blocks(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """모델에 relationship()이 없으므로 이건 DB의 CASCADE가 하는 일이다.

    ORM이 대신 지워주고 있는 것이 아니라는 뜻이라, 여기서 확인하지 않으면
    마이그레이션에서 ondelete를 빠뜨려도 아무도 모른다.
    """
    headers = await auth_headers(client, "owner@example.com")
    trip_id = await create_trip(client, headers)
    await put_blocks(client, headers, trip_id, BLOCK)

    await client.delete(f"/trips/{trip_id}", headers=headers)

    count = await db_session.scalar(select(func.count()).select_from(Block))
    assert count == 0
