"""가입 → 로그인 → /me 왕복. 에러 코드 표준(409/401)을 코드가 아니라 여기서 붙잡는다."""

from httpx import AsyncClient

EMAIL = "tester@example.com"
PASSWORD = "test-password-1234"


async def signup(client: AsyncClient, email: str = EMAIL, password: str = PASSWORD):
    return await client.post("/auth/signup", json={"email": email, "password": password})


async def login(client: AsyncClient, email: str = EMAIL, password: str = PASSWORD):
    return await client.post(
        "/auth/login", data={"username": email, "password": password}
    )


async def test_signup_returns_created_user_without_password(client: AsyncClient) -> None:
    response = await signup(client)

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == EMAIL
    assert "id" in body
    # UserRead 경계가 해시를 새지 않는지 — 응답 스키마의 존재 이유다
    assert "hashed_password" not in body
    assert "password" not in body


async def test_signup_duplicate_email_returns_409(client: AsyncClient) -> None:
    await signup(client)

    response = await signup(client)

    assert response.status_code == 409


async def test_signup_rejects_short_password(client: AsyncClient) -> None:
    response = await signup(client, password="short")

    assert response.status_code == 422


async def test_login_returns_bearer_token(client: AsyncClient) -> None:
    await signup(client)

    response = await login(client)

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]


async def test_login_with_wrong_password_returns_401(client: AsyncClient) -> None:
    await signup(client)

    response = await login(client, password="wrong-password-1234")

    assert response.status_code == 401


async def test_me_returns_current_user(client: AsyncClient) -> None:
    await signup(client)
    token = (await login(client)).json()["access_token"]

    response = await client.get(
        "/auth/me", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    assert response.json()["email"] == EMAIL


async def test_me_without_token_returns_401(client: AsyncClient) -> None:
    response = await client.get("/auth/me")

    assert response.status_code == 401


async def test_me_with_garbage_token_returns_401(client: AsyncClient) -> None:
    response = await client.get(
        "/auth/me", headers={"Authorization": "Bearer not-a-real-token"}
    )

    assert response.status_code == 401
