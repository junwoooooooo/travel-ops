"""LLM을 부르는 단 하나의 통로. 스키마 강제와 계측이 여기 모여 있다.

`integrations/http.py`와 같은 자리이지만 한 층 위(`core/`)에 있다. 이유는 의존 방향이다 —
http는 우리가 직접 조립하는 HTTP 호출이고, 여기는 벤더 SDK가 커넥션·재시도까지 들고 있는
**설비**다. 도메인(`planning`)은 SDK를 모르고 이 파일의 함수 하나만 안다.

**이 파일은 "무엇을 물어볼지"를 모른다.** 프롬프트도, 되묻기 판단도 도메인 몫이다.
여기가 책임지는 것은 셋뿐이다: 스키마에 맞는 값을 돌려주거나, 못 받았다고 예외를 올리거나,
얼마나 걸리고 얼마나 썼는지 남기거나 (ADR-0011).
"""

import logging
import time
from typing import TypeVar

import openai
from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

from app.config import settings

logger = logging.getLogger(__name__)

# 사람이 기다리는 시간이지만 http.py(read 3초)와 예산이 다르다. LLM은 수십 초가 정상이라
# (R1) 짧게 잡으면 정상 응답을 우리가 먼저 끊는다. nginx가 300초까지 열어 두었으므로
# (nginx/default.conf) 그 안쪽에서 넉넉히 잡는다
_TIMEOUT_SECONDS = 60.0

# SDK가 429·5xx·연결 실패에만 재시도한다 — http.py의 _RETRYABLE_STATUS와 같은 정책이다.
# 2회 재시도 = 최대 3회 시도로 맞춰 두 통로의 동작을 일치시킨다
_MAX_RETRIES = 2

_client: AsyncOpenAI | None = None

# 스키마 클래스를 그대로 돌려주기 위한 타입 변수. 호출자는 캐스팅 없이 자기 모델을 받는다
SchemaT = TypeVar("SchemaT", bound=BaseModel)


class LlmNotConfigured(RuntimeError):
    """API 키가 비었다. 네트워크를 타기 전에 즉시 실패한다 (KakaoNotConfigured와 같은 규칙)."""


class LlmUnavailable(RuntimeError):
    """쓸 수 있는 답을 못 받았다.

    장애(타임아웃·5xx·쿼터)와 계약 위반(스키마에 안 맞는 응답·중도 잘림·거부)을 한 예외로
    묶는다. 예외를 둘로 나눠도 호출자가 할 수 있는 일이 "잠시 후 재시도"로 같아서,
    구분이 분기를 만들지 못하고 클래스 수만 늘린다 (R3).

    `reason`으로는 구별된다 — 로그에서 "저쪽이 아픈 것"과 "우리 스키마가 안 맞는 것"은
    대응이 다르기 때문이다.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(f"LLM 응답을 쓸 수 없다 ({reason})")
        self.reason = reason


def _get_client() -> AsyncOpenAI:
    """지연 생성 싱글턴. 테스트는 이 전역을 MockTransport 클라이언트로 갈아끼운다.

    키가 없을 때 여기서 죽지 않는 이유: 이 함수는 앱 기동 시점에 불릴 수 있고, 키가 없다고
    로그인·여행 조회까지 멈출 이유가 없다. 실패는 complete_json에서 난다 (ADR-0011).
    """
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            timeout=_TIMEOUT_SECONDS,
            max_retries=_MAX_RETRIES,
        )
    return _client


async def complete_json(
    *,
    name: str,
    instructions: str,
    user_input: str,
    schema: type[SchemaT],
) -> SchemaT:
    """자연어 → `schema` 인스턴스. 못 받으면 LlmUnavailable.

    구조화 출력(`text_format`)으로 모델이 스키마를 벗어난 JSON을 만들지 못하게 막고,
    돌아온 값은 Pydantic이 한 번 더 검증한다. 두 번 거르는 이유는 값의 **모양**만
    보장될 뿐 **내용**은 여전히 비결정적이기 때문이다 — 내용 판단은 호출자의 코드가 한다
    (ADR-0007: 말은 LLM, 계산은 코드).

    `name`은 로그용 이름이다(예: "planning.parse"). **프롬프트 원문과 사용자 입력은
    로그에 남기지 않는다** — 여행 계획 요청에는 동행·예산 같은 개인정보가 섞이고,
    `http.py`가 URL을 안 찍는 것과 같은 이유다 (CLAUDE.md 절대 규칙).
    """
    if not settings.openai_api_key:
        raise LlmNotConfigured(
            "OPENAI_API_KEY가 비어 있다. .env에 키를 넣어야 일정 생성이 된다"
        )

    started = time.perf_counter()
    try:
        response = await _get_client().responses.parse(
            model=settings.openai_model,
            instructions=instructions,
            input=user_input,
            text_format=schema,
        )
    except openai.APIError as exc:
        # 타임아웃·연결 실패·4xx·5xx·429가 전부 여기로 온다. SDK가 이미 재시도할 것은
        # 재시도한 뒤이므로, 여기 도달했다는 건 최종 실패라는 뜻이다
        logger.warning("%s 호출 실패: %s", name, type(exc).__name__)
        raise LlmUnavailable("upstream") from exc
    except ValidationError as exc:
        # 구조화 출력이 있어도 0이 되지는 않는다(중도 잘림 등). 여기까지 오면 계약 위반이다
        logger.error("%s 응답이 스키마를 벗어났다", name)
        raise LlmUnavailable("schema") from exc

    elapsed_ms = (time.perf_counter() - started) * 1000
    usage = response.usage
    logger.info(
        "%s 완료 (%.0fms, model=%s, in=%s, out=%s)",
        name,
        elapsed_ms,
        response.model,
        usage.input_tokens if usage else "?",
        usage.output_tokens if usage else "?",
    )

    if response.status != "completed":
        # 출력 토큰 상한에 걸려 잘렸거나 안전 필터에 막혔다. 앞부분만 파싱된 반쪽짜리 값을
        # 정상처럼 돌려주면 일정이 조용히 잘린 채로 저장된다
        logger.error("%s 미완결 응답 (status=%s)", name, response.status)
        raise LlmUnavailable(f"status={response.status}")

    parsed = response.output_parsed
    if parsed is None:
        # 모델이 거부했거나 파싱할 메시지가 없었다
        raise LlmUnavailable("empty")
    return parsed


async def aclose() -> None:
    """lifespan 종료용. 다음 호출이 새 클라이언트를 만들도록 전역도 비운다."""
    global _client
    if _client is not None:
        await _client.close()
        _client = None
