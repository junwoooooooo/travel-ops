"""planning의 계약. 두 종류가 섞여 있어 구분해 둔다.

- `TripSpec`은 **LLM에게 주는 스키마**다. 제약(ge·min_length)을 걸지 않는다 — OpenAI
  구조화 출력의 엄격 모드가 받아 주는 키워드가 한정적이고, 무엇보다 값의 **내용**을
  판정하는 일은 코드 몫이기 때문이다 (ADR-0007, ADR-0011).
- 나머지는 **우리 HTTP 계약**이다. 여기엔 평소대로 제약을 건다.
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

# 한 문장 요청이다. 상한이 없으면 공짜로 토큰을 태울 수 있다
MAX_TEXT_LENGTH = 2000


class ParseRequest(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_TEXT_LENGTH)


class TripSpec(BaseModel):
    """LLM이 자연어에서 뽑아낸 여행 요청. **모르는 값은 None이다.**

    None과 "빈 값"을 구별하는 것이 이 스키마의 전부다. LLM이 모르는 걸 지어내는 대신
    None을 주게 만들어야, 무엇을 되물을지 코드가 판정할 수 있다.

    필드 이름을 `trips.TripCreate`에 맞춰 두었다 — 세션 13에서 여행을 만들 때
    이름 대응표를 따로 들고 다니지 않게 된다 (`kakao.PlaceCandidate`와 같은 요령).
    """

    destination: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    # 원 단위 정수. "40만원" → 400000
    budget_total: int | None = None
    themes: list[str] = []


class Question(BaseModel):
    """되묻기 한 건. `field`가 붙어 있어 클라이언트가 어느 칸을 채울지 안다."""

    field: str
    question: str


class ParseResponse(BaseModel):
    """`status`가 ready면 `questions`는 비어 있고, needs_input이면 하나 이상 있다.

    **불변식: `spec`에서 None이 아닌 값은 전부 신뢰할 수 있다.** 되묻기 대상이 된 필드는
    None으로 지워서 내보낸다 — 예컨대 LLM이 뒤집힌 날짜를 주면 그 두 값을 남긴 채
    "다시 알려 달라"고 하지 않고, 아예 모르는 값으로 되돌린다. 그래야 클라이언트가
    받은 spec을 그대로 화면에 채워도 거짓이 섞이지 않는다.
    """

    status: Literal["ready", "needs_input"]
    spec: TripSpec
    questions: list[Question] = []
