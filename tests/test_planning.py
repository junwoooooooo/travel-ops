"""planning 층. 붙잡는 계약은 셋이다.

1. **판단은 코드가 한다** — 무엇이 부족한지, 무엇이 말이 안 되는지를 LLM에게 묻지 않는다.
   그래서 `missing_fields` 테스트에는 LLM이 아예 등장하지 않는다 (ADR-0011).
2. **되묻기는 오류가 아니다** — 정보가 모자라면 200과 질문이지 4xx가 아니다.
3. **LLM이 죽어도 앱은 산다** — 키가 없어도 기동하고, 장애는 503 하나로 수렴한다.

바깥 네트워크를 타지 않는다. 게이트웨이 테스트는 httpx2.MockTransport를 SDK 전송 계층에
끼우고(재시도·파싱이라는 진짜 경로가 그대로 돈다), 도메인 테스트는 게이트웨이 함수를
갈아끼운다 — 도메인은 어느 공급자를 쓰는지 몰라야 하기 때문이다.
"""

import logging
from collections.abc import Callable
from datetime import date, timedelta

import httpx2
import pytest
from httpx import AsyncClient
from openai import AsyncOpenAI

from app.config import settings
from app.core import llm
from app.planning import service
from app.planning.schemas import TripSpec

PASSWORD = "test-password-1234"

# 세션 12의 기준 문장. Phase 1 DoD가 이 문장을 쓴다
BUSAN_SPEC = TripSpec(
    destination="부산",
    start_date=date(2026, 10, 3),
    end_date=date(2026, 10, 5),
    budget_total=400_000,
    themes=["미식"],
)
TODAY = date(2026, 9, 16)


# ---------------------------------------------------------------- 공용 도구


@pytest.fixture
def api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """키가 있는 상태. 없을 때의 동작은 별도 테스트가 본다."""
    monkeypatch.setattr(settings, "openai_api_key", "test-key-not-a-real-one")


def install_llm(
    monkeypatch: pytest.MonkeyPatch, handler: Callable
) -> list[httpx2.Request]:
    """SDK 전역 클라이언트를 MockTransport로 갈아끼우고, 오간 요청을 기록해 돌려준다.

    리스트의 길이가 곧 "네트워크를 몇 번 탔는가"다 — 재시도 횟수를 이 숫자로 판정한다.
    (integrations 테스트의 install과 같은 요령. 다만 SDK가 httpx2를 쓴다)
    """
    calls: list[httpx2.Request] = []

    def recording(request: httpx2.Request) -> httpx2.Response:
        calls.append(request)
        return handler(request)

    monkeypatch.setattr(
        llm,
        "_client",
        AsyncOpenAI(
            api_key="test-key-not-a-real-one",
            max_retries=llm._MAX_RETRIES,
            http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(recording)),
        ),
    )
    return calls


def responds(spec: TripSpec, *, status: str = "completed") -> dict:
    """OpenAI Responses API 응답 한 건의 모양."""
    return {
        "id": "resp_test",
        "object": "response",
        "created_at": 1,
        "status": status,
        "model": "gpt-5.5",
        "output": [
            {
                "id": "msg_test",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [
                    {
                        "type": "output_text",
                        "text": spec.model_dump_json(),
                        "annotations": [],
                    }
                ],
            }
        ],
        "parallel_tool_calls": False,
        "tool_choice": "auto",
        "tools": [],
        "usage": {
            "input_tokens": 120,
            "output_tokens": 30,
            "total_tokens": 150,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 0},
        },
    }


def stub_llm(
    monkeypatch: pytest.MonkeyPatch,
    *,
    spec: TripSpec | None = None,
    error: Exception | None = None,
    captured: dict | None = None,
) -> None:
    """도메인 테스트용. 공급자를 모르는 자리에서 값만 갈아끼운다."""

    async def fake_complete_json(*, name, instructions, user_input, schema):
        if captured is not None:
            captured["instructions"] = instructions
            captured["user_input"] = user_input
        if error is not None:
            raise error
        return spec

    monkeypatch.setattr(llm, "complete_json", fake_complete_json)


async def auth_headers(client: AsyncClient, email: str) -> dict[str, str]:
    await client.post("/auth/signup", json={"email": email, "password": PASSWORD})
    token = (
        await client.post("/auth/login", data={"username": email, "password": PASSWORD})
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# ------------------------------------------------- 판단은 코드가 한다 (LLM 없음)


def test_complete_spec_asks_nothing() -> None:
    assert service.missing_fields(BUSAN_SPEC, today=TODAY) == []


def test_blank_destination_counts_as_missing() -> None:
    spec = BUSAN_SPEC.model_copy(update={"destination": "   "})

    assert service.missing_fields(spec, today=TODAY) == ["destination"]


def test_reversed_dates_make_both_dates_unknown() -> None:
    """어느 쪽이 틀렸는지 알 수 없다. 조용히 뒤집어 고치면 틀린 일정이 나온다."""
    spec = BUSAN_SPEC.model_copy(
        update={"start_date": date(2026, 10, 5), "end_date": date(2026, 10, 3)}
    )

    assert service.missing_fields(spec, today=TODAY) == ["start_date", "end_date"]


def test_past_start_date_is_asked_again() -> None:
    """연도를 빠뜨린 문장에서 잘 나온다."""
    spec = BUSAN_SPEC.model_copy(
        update={"start_date": date(2025, 10, 3), "end_date": date(2025, 10, 5)}
    )

    assert service.missing_fields(spec, today=TODAY) == ["start_date"]


def test_today_itself_is_allowed() -> None:
    spec = BUSAN_SPEC.model_copy(update={"start_date": TODAY, "end_date": TODAY})

    assert service.missing_fields(spec, today=TODAY) == []


def test_negative_budget_is_treated_as_unknown() -> None:
    """사용자가 그렇게 말한 게 아니라 LLM이 잘못 읽은 것이다."""
    spec = BUSAN_SPEC.model_copy(update={"budget_total": -1})

    assert service.missing_fields(spec, today=TODAY) == ["budget_total"]


def test_zero_budget_is_a_real_answer() -> None:
    """0원은 "예산 미정"이 아니다. None과 구별한다."""
    spec = BUSAN_SPEC.model_copy(update={"budget_total": 0})

    assert service.missing_fields(spec, today=TODAY) == []


def test_only_one_date_still_asks_for_the_other() -> None:
    """"2박3일"만 알고 출발일을 모르는 문장. 기간을 추측해 채우지 않는다."""
    spec = BUSAN_SPEC.model_copy(update={"end_date": None})

    assert service.missing_fields(spec, today=TODAY) == ["end_date"]


def test_empty_spec_asks_for_everything() -> None:
    assert service.missing_fields(TripSpec(), today=TODAY) == [
        "destination",
        "budget_total",
        "start_date",
        "end_date",
    ]


# ------------------------------------------------------------- 되묻기 분기


async def test_ready_when_nothing_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    stub_llm(monkeypatch, spec=BUSAN_SPEC)

    result = await service.parse_intent("부산 2박3일 미식, 40만원", today=TODAY)

    assert result.status == "ready"
    assert result.questions == []
    assert result.spec.destination == "부산"
    assert result.spec.budget_total == 400_000
    assert result.spec.themes == ["미식"]


async def test_missing_budget_returns_a_question(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_llm(monkeypatch, spec=BUSAN_SPEC.model_copy(update={"budget_total": None}))

    result = await service.parse_intent("부산 2박3일 미식", today=TODAY)

    assert result.status == "needs_input"
    assert [q.field for q in result.questions] == ["budget_total"]
    assert result.questions[0].question


async def test_untrustworthy_values_are_erased_from_the_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ParseResponse의 불변식 — None이 아닌 값은 전부 믿을 수 있다.

    뒤집힌 날짜를 그대로 돌려주면서 되물으면, 클라이언트가 그 값을 화면에 채우는 순간
    거짓이 사용자에게 보인다.
    """
    stub_llm(
        monkeypatch,
        spec=BUSAN_SPEC.model_copy(
            update={"start_date": date(2026, 10, 5), "end_date": date(2026, 10, 3)}
        ),
    )

    result = await service.parse_intent("부산 여행", today=TODAY)

    assert result.status == "needs_input"
    assert result.spec.start_date is None
    assert result.spec.end_date is None
    # 멀쩡한 값까지 지우지는 않는다
    assert result.spec.destination == "부산"


async def test_prompt_carries_today_so_relative_dates_resolve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """"다음 주 금요일"을 풀려면 모델이 오늘을 알아야 한다."""
    captured: dict = {}
    stub_llm(monkeypatch, spec=BUSAN_SPEC, captured=captured)

    await service.parse_intent("다음 주 금요일부터 부산", today=TODAY)

    assert TODAY.isoformat() in captured["instructions"]
    assert captured["user_input"] == "다음 주 금요일부터 부산"


# ------------------------------------------------------- 게이트웨이 (core/llm.py)


async def test_missing_key_fails_before_touching_the_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = install_llm(monkeypatch, lambda request: httpx2.Response(200, json={}))
    monkeypatch.setattr(settings, "openai_api_key", "")

    with pytest.raises(llm.LlmNotConfigured):
        await llm.complete_json(
            name="t", instructions="i", user_input="u", schema=TripSpec
        )

    assert calls == []


async def test_structured_response_becomes_a_schema_instance(
    monkeypatch: pytest.MonkeyPatch, api_key: None
) -> None:
    install_llm(
        monkeypatch, lambda request: httpx2.Response(200, json=responds(BUSAN_SPEC))
    )

    spec = await llm.complete_json(
        name="t", instructions="i", user_input="u", schema=TripSpec
    )

    assert isinstance(spec, TripSpec)
    assert spec.destination == "부산"
    assert spec.start_date == date(2026, 10, 3)


async def test_server_errors_are_retried_then_give_up(
    monkeypatch: pytest.MonkeyPatch, api_key: None
) -> None:
    """http.py와 같은 정책 — 최대 3회 시도."""
    calls = install_llm(monkeypatch, lambda request: httpx2.Response(503))

    with pytest.raises(llm.LlmUnavailable) as exc:
        await llm.complete_json(
            name="t", instructions="i", user_input="u", schema=TripSpec
        )

    assert exc.value.reason == "upstream"
    assert len(calls) == 3


async def test_client_errors_are_not_retried(
    monkeypatch: pytest.MonkeyPatch, api_key: None
) -> None:
    """400을 세 번 물어도 답은 같다. 사용자 대기만 3배가 된다."""
    calls = install_llm(monkeypatch, lambda request: httpx2.Response(400, json={}))

    with pytest.raises(llm.LlmUnavailable):
        await llm.complete_json(
            name="t", instructions="i", user_input="u", schema=TripSpec
        )

    assert len(calls) == 1


async def test_incomplete_response_is_rejected(
    monkeypatch: pytest.MonkeyPatch, api_key: None
) -> None:
    """출력 상한에 걸려 잘린 응답을 정상처럼 쓰면 일정이 조용히 반쪽이 된다."""

    def truncated(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=responds(BUSAN_SPEC, status="incomplete"))

    install_llm(monkeypatch, truncated)

    with pytest.raises(llm.LlmUnavailable) as exc:
        await llm.complete_json(
            name="t", instructions="i", user_input="u", schema=TripSpec
        )

    assert "incomplete" in exc.value.reason


async def test_logs_leak_neither_the_key_nor_the_user_sentence(
    monkeypatch: pytest.MonkeyPatch, api_key: None, caplog: pytest.LogCaptureFixture
) -> None:
    """여행 요청에는 동행·예산 같은 개인정보가 섞인다 (CLAUDE.md 절대 규칙)."""
    install_llm(
        monkeypatch, lambda request: httpx2.Response(200, json=responds(BUSAN_SPEC))
    )
    secret_sentence = "부모님 모시고 가는 여행이라 예산은 40만원"

    with caplog.at_level(logging.DEBUG, logger="app.core.llm"):
        await llm.complete_json(
            name="planning.parse",
            instructions="비밀 프롬프트 본문",
            user_input=secret_sentence,
            schema=TripSpec,
        )

    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert secret_sentence not in logged
    assert "비밀 프롬프트 본문" not in logged
    assert settings.openai_api_key not in logged
    # 계측은 남아야 한다 — 없으면 Phase 4가 붙일 데가 없다
    assert "planning.parse" in logged


# ------------------------------------------------------------------ 라우터


async def test_parse_without_token_returns_401(client: AsyncClient) -> None:
    response = await client.post("/planning/parse", json={"text": "부산 2박3일"})

    assert response.status_code == 401


async def test_parse_returns_ready_plan(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers = await auth_headers(client, "planner@example.com")
    # 라우터는 서버 시계를 쓴다 — 오늘이 언제든 미래인 날짜로 고정한다
    future = date.today() + timedelta(days=30)
    stub_llm(
        monkeypatch,
        spec=BUSAN_SPEC.model_copy(
            update={"start_date": future, "end_date": future + timedelta(days=2)}
        ),
    )

    response = await client.post(
        "/planning/parse", json={"text": "부산 2박3일 미식, 40만원"}, headers=headers
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["questions"] == []
    assert body["spec"]["destination"] == "부산"


async def test_parse_returns_questions_not_an_error(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """되묻기는 정상 분기다 — weather 실패가 None인 것과 같다 (ADR-0010)."""
    headers = await auth_headers(client, "asker@example.com")
    stub_llm(monkeypatch, spec=TripSpec(destination="부산"))

    response = await client.post(
        "/planning/parse", json={"text": "부산 가고 싶어"}, headers=headers
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "needs_input"
    assert {q["field"] for q in body["questions"]} == {
        "budget_total",
        "start_date",
        "end_date",
    }


async def test_llm_outage_returns_503(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers = await auth_headers(client, "unlucky@example.com")
    stub_llm(monkeypatch, error=llm.LlmUnavailable("upstream"))

    response = await client.post(
        "/planning/parse", json={"text": "부산 2박3일"}, headers=headers
    )

    assert response.status_code == 503


async def test_missing_key_returns_503_but_the_app_is_up(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """키가 없다고 로그인·여행 조회까지 멈출 이유가 없다 (ADR-0010의 연장)."""
    headers = await auth_headers(client, "nokey@example.com")
    monkeypatch.setattr(settings, "openai_api_key", "")

    response = await client.post(
        "/planning/parse", json={"text": "부산 2박3일"}, headers=headers
    )

    assert response.status_code == 503
    # 같은 앱의 다른 입구는 멀쩡하다
    assert (await client.get("/auth/me", headers=headers)).status_code == 200
    assert (await client.get("/health")).status_code == 200


async def test_empty_text_is_rejected_as_validation_error(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers = await auth_headers(client, "empty@example.com")
    stub_llm(monkeypatch, spec=BUSAN_SPEC)

    response = await client.post("/planning/parse", json={"text": ""}, headers=headers)

    assert response.status_code == 422


async def test_overlong_text_is_rejected_before_burning_tokens(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers = await auth_headers(client, "long@example.com")
    called: dict = {}
    stub_llm(monkeypatch, spec=BUSAN_SPEC, captured=called)

    response = await client.post(
        "/planning/parse", json={"text": "부" * 5000}, headers=headers
    )

    assert response.status_code == 422
    assert called == {}
