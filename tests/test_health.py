"""배포 검증이 딛고 서는 계약. CD 워크플로가 이 응답의 commit을 이번 커밋과 대조한다."""

from httpx import AsyncClient

from app.config import Settings, settings


async def test_health_reports_status_and_commit(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    # 키 이름이 바뀌면 워크플로의 대조가 조용히 영영 실패한다 — 여기서 잡는다
    assert body["commit"] == settings.git_sha


def test_git_sha_has_a_default() -> None:
    """빌드 인자가 없는 환경(로컬·CI)에서도 앱이 떠야 한다.

    기본값이 사라지면 .env에 GIT_SHA가 없는 순간 import 시점에 죽는다.
    런타임 값이 아니라 필드 기본값을 본다 — 셸에 GIT_SHA가 있어도 흔들리지 않는다.
    """
    assert Settings.model_fields["git_sha"].default == "unknown"
