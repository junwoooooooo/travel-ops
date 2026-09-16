"""자연어 요청 → 검증된 TripSpec, 또는 되묻기.

**이 파일의 설계 한 줄: LLM에게 "정보가 충분하냐"고 묻지 않는다.**

LLM은 문장에서 값을 뽑기만 하고(모르면 None), 무엇이 부족한지·무엇이 말이 안 되는지는
아래 `missing_fields`가 판정한다. ADR-0007이 금지한 LLM 자체검증을 피하는 것이기도 하고,
실용적으로도 이 판정은 공짜이고 결정적이며 테스트에 LLM이 필요 없다 (ADR-0011).
"""

import logging
from datetime import date

from app.core import llm
from app.planning.schemas import ParseResponse, Question, TripSpec

logger = logging.getLogger(__name__)

# 일정을 만들려면 최소한 이 넷이 있어야 한다. 취향(themes)은 없어도 일정이 나온다
_QUESTIONS: dict[str, str] = {
    "destination": "어디로 가시나요? (예: 부산)",
    "start_date": "언제 출발하세요? (예: 2026-10-03, 또는 '다음 주 금요일')",
    "end_date": "언제 돌아오세요? (예: 2026-10-05)",
    "budget_total": "예산은 얼마로 잡을까요? (예: 40만원)",
}

_INSTRUCTIONS = """\
너는 한국어 여행 요청 문장에서 값을 뽑아내는 추출기다. 조언하거나 일정을 제안하지 마라.

오늘은 {today}다. "다음 주 금요일" 같은 상대 날짜는 이 날짜를 기준으로 계산한다.

규칙:
- 문장에 없는 값은 절대 지어내지 말고 null로 둔다. 추측도 하지 않는다.
- destination: 도시나 지역 이름만 (예: "부산", "제주").
- start_date / end_date: YYYY-MM-DD. "2박3일"처럼 기간만 있고 출발일이 없으면
  둘 다 null로 둔다. 출발일을 알 때만 "2박3일" = 출발일 + 2일로 계산한다.
- budget_total: 원 단위 정수. "40만원" -> 400000, "1인당"이라는 말이 없으면 총액으로 본다.
- themes: 문장에 드러난 취향 키워드 짧게 (예: ["미식"], ["휴양", "온천"]). 없으면 빈 배열.
"""


def missing_fields(spec: TripSpec, *, today: date) -> list[str]:
    """되물어야 할 필드 이름. LLM을 부르지 않는 순수 함수다.

    "비어 있다"뿐 아니라 **"말이 안 된다"도 모름으로 친다.** 뒤집힌 날짜나 음수 예산은
    사용자가 그렇게 말한 게 아니라 LLM이 잘못 읽은 것이고, 우리가 할 수 있는 최선은
    되묻는 것이다 — 조용히 고쳐서 진행하면 틀린 일정이 나온다 (R4).
    """
    missing: list[str] = []

    if not (spec.destination or "").strip():
        missing.append("destination")

    # 음수 예산은 LLM의 오독이다. 0원은 "예산 없음"이 아니라 유효한 입력으로 본다
    if spec.budget_total is None or spec.budget_total < 0:
        missing.append("budget_total")

    missing.extend(_missing_dates(spec, today=today))
    return missing


def _missing_dates(spec: TripSpec, *, today: date) -> list[str]:
    """날짜 둘은 서로 얽혀 있어 따로 판정한다."""
    if spec.start_date is None or spec.end_date is None:
        # 한쪽만 있어도 남은 한쪽을 물어야 한다. 기간을 추측해 채우지 않는다
        return [f for f in ("start_date", "end_date") if getattr(spec, f) is None]

    if spec.end_date < spec.start_date:
        # 어느 쪽이 틀렸는지 알 방법이 없다. 둘 다 모름으로 되돌린다
        return ["start_date", "end_date"]

    if spec.start_date < today:
        # 지나간 날짜로는 일정을 만들 수 없다. 연도를 빠뜨린 문장에서 잘 나온다
        return ["start_date"]

    return []


def _forget(spec: TripSpec, missing: list[str]) -> TripSpec:
    """되묻기 대상 필드를 None으로 지운다.

    ParseResponse의 불변식("None이 아닌 값은 신뢰할 수 있다")을 지키는 자리다.
    뒤집힌 날짜를 그대로 돌려주면서 "다시 알려 달라"고 하면, 클라이언트가 그 값을
    화면에 채우는 순간 거짓이 사용자에게 보인다.
    """
    cleaned = spec.model_copy(update={field: None for field in missing})
    # 공백만 든 문자열도 여기서 정리한다 — destination이 " "인 채로 통과하면
    # 나중에 카카오 검색어가 공백이 된다
    if cleaned.destination is not None:
        cleaned.destination = cleaned.destination.strip() or None
    cleaned.themes = [t.strip() for t in cleaned.themes if t.strip()]
    return cleaned


async def parse_intent(text: str, *, today: date) -> ParseResponse:
    """한 문장 → ready 또는 needs_input. LLM 장애는 예외로 올라간다.

    `today`를 인자로 받는 이유는 테스트 결정성이다. 라우터가 서버 시계를 넣는다 —
    클라이언트가 보낸 날짜를 믿으면 과거 날짜 검사를 우회할 수 있다.
    """
    spec = await llm.complete_json(
        name="planning.parse",
        instructions=_INSTRUCTIONS.format(today=today.isoformat()),
        user_input=text,
        schema=TripSpec,
    )

    missing = missing_fields(spec, today=today)
    cleaned = _forget(spec, missing)

    if not missing:
        return ParseResponse(status="ready", spec=cleaned)

    # 되묻기는 오류가 아니라 정상 분기다 — weather 실패가 None인 것과 같다 (ADR-0010).
    # 로그에는 "무엇이 비었는지"만 남긴다. 사용자 문장 원문은 남기지 않는다
    logger.info("planning.parse 되묻기 %s", missing)
    return ParseResponse(
        status="needs_input",
        spec=cleaned,
        questions=[Question(field=f, question=_QUESTIONS[f]) for f in missing],
    )
