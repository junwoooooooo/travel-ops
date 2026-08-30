"""여행 보관 금고. 여기서 붙잡는 계약은 두 가지다 — CRUD가 도는 것, 그리고 남의 것이 안 보이는 것."""

from httpx import AsyncClient

PASSWORD = "test-password-1234"
TRIP = {
    "title": "오사카 미식",
    "destination": "오사카",
    "start_date": "2026-10-01",
    "end_date": "2026-10-04",
    "budget_total": 1_500_000,
}


async def auth_headers(client: AsyncClient, email: str) -> dict[str, str]:
    """가입 → 로그인 → Authorization 헤더. 소유권 테스트는 계정이 둘 필요하다."""
    await client.post("/auth/signup", json={"email": email, "password": PASSWORD})
    token = (
        await client.post(
            "/auth/login", data={"username": email, "password": PASSWORD}
        )
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


async def create_trip(client: AsyncClient, headers: dict[str, str], **overrides):
    return await client.post("/trips", json=TRIP | overrides, headers=headers)


async def test_create_returns_trip(client: AsyncClient) -> None:
    headers = await auth_headers(client, "owner@example.com")

    response = await create_trip(client, headers)

    assert response.status_code == 201
    body = response.json()
    assert body["title"] == TRIP["title"]
    assert body["budget_total"] == 1_500_000
    # 자기 것만 보이므로 소유자 id는 응답에 담지 않는다
    assert "user_id" not in body


async def test_create_without_token_returns_401(client: AsyncClient) -> None:
    response = await client.post("/trips", json=TRIP)

    assert response.status_code == 401


async def test_create_with_reversed_dates_returns_422(client: AsyncClient) -> None:
    headers = await auth_headers(client, "owner@example.com")

    response = await create_trip(client, headers, end_date="2026-09-30")

    assert response.status_code == 422


async def test_create_with_negative_budget_returns_422(client: AsyncClient) -> None:
    headers = await auth_headers(client, "owner@example.com")

    response = await create_trip(client, headers, budget_total=-1)

    assert response.status_code == 422


async def test_list_returns_only_my_trips(client: AsyncClient) -> None:
    owner = await auth_headers(client, "owner@example.com")
    stranger = await auth_headers(client, "stranger@example.com")
    await create_trip(client, owner, title="내 여행")
    await create_trip(client, stranger, title="남의 여행")

    response = await client.get("/trips", headers=owner)

    assert response.status_code == 200
    titles = [trip["title"] for trip in response.json()]
    assert titles == ["내 여행"]


async def test_read_own_trip(client: AsyncClient) -> None:
    headers = await auth_headers(client, "owner@example.com")
    trip_id = (await create_trip(client, headers)).json()["id"]

    response = await client.get(f"/trips/{trip_id}", headers=headers)

    assert response.status_code == 200
    assert response.json()["id"] == trip_id


async def test_others_trip_is_indistinguishable_from_missing(client: AsyncClient) -> None:
    """이 프로젝트의 인가 계약. 403이면 "있긴 있다"를 알려주는 셈이다."""
    owner = await auth_headers(client, "owner@example.com")
    stranger = await auth_headers(client, "stranger@example.com")
    trip_id = (await create_trip(client, owner)).json()["id"]

    others = await client.get(f"/trips/{trip_id}", headers=stranger)
    missing = await client.get("/trips/999999", headers=stranger)

    assert others.status_code == missing.status_code == 404
    # 본문까지 같아야 한다 — 메시지가 갈라지면 존재 여부가 새어 나간다
    assert others.json() == missing.json()


async def test_others_trip_cannot_be_updated_or_deleted(client: AsyncClient) -> None:
    owner = await auth_headers(client, "owner@example.com")
    stranger = await auth_headers(client, "stranger@example.com")
    trip_id = (await create_trip(client, owner)).json()["id"]

    patched = await client.patch(
        f"/trips/{trip_id}", json={"title": "가로채기"}, headers=stranger
    )
    deleted = await client.delete(f"/trips/{trip_id}", headers=stranger)

    assert patched.status_code == 404
    assert deleted.status_code == 404
    # 정말로 안 바뀌었는지는 주인 눈으로 확인한다
    assert (await client.get(f"/trips/{trip_id}", headers=owner)).json()["title"] == (
        TRIP["title"]
    )


async def test_patch_changes_only_given_fields(client: AsyncClient) -> None:
    headers = await auth_headers(client, "owner@example.com")
    trip_id = (await create_trip(client, headers)).json()["id"]

    response = await client.patch(
        f"/trips/{trip_id}", json={"title": "오사카 재도전"}, headers=headers
    )

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "오사카 재도전"
    assert body["destination"] == TRIP["destination"]
    assert body["end_date"] == TRIP["end_date"]


async def test_patch_one_date_into_reversed_range_returns_422(client: AsyncClient) -> None:
    """스키마가 아니라 service가 잡는 경로 — 저장된 start_date와 합쳐봐야 알 수 있다."""
    headers = await auth_headers(client, "owner@example.com")
    trip_id = (await create_trip(client, headers)).json()["id"]

    response = await client.patch(
        f"/trips/{trip_id}", json={"end_date": "2026-09-01"}, headers=headers
    )

    assert response.status_code == 422


async def test_delete_removes_trip(client: AsyncClient) -> None:
    headers = await auth_headers(client, "owner@example.com")
    trip_id = (await create_trip(client, headers)).json()["id"]

    deleted = await client.delete(f"/trips/{trip_id}", headers=headers)

    assert deleted.status_code == 204
    assert (await client.get(f"/trips/{trip_id}", headers=headers)).status_code == 404
