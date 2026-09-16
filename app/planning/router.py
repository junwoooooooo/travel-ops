from datetime import date

from fastapi import APIRouter, HTTPException, status

from app.auth.service import CurrentUser
from app.core import llm
from app.planning import service
from app.planning.schemas import ParseRequest, ParseResponse

router = APIRouter(prefix="/planning", tags=["planning"])

# 키 없음·타임아웃·5xx·계약 위반을 한 코드로 묶는다. 넷 다 사용자가 할 수 있는 일이
# "잠시 후 재시도"로 같아서, 코드를 나눠도 클라이언트의 분기가 늘지 않는다 (ADR-0011).
# 어느 쪽이었는지는 LlmUnavailable.reason으로 로그에 남는다
_UNAVAILABLE = HTTPException(
    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
    detail="Planning is temporarily unavailable. Please try again.",
)


@router.post("/parse", response_model=ParseResponse)
async def parse(payload: ParseRequest, current_user: CurrentUser) -> ParseResponse:
    """자연어 요청을 TripSpec으로 바꾼다. 정보가 모자라면 질문을 돌려준다.

    DB를 쓰지 않는다 — 아직 여행이 만들어지기 전 단계다. `current_user`는 저장할 게
    있어서가 아니라 **토큰을 태우는 엔드포인트라서** 받는다.

    `today`는 서버 시계에서만 온다. 클라이언트가 보내게 하면 과거 날짜 검사를
    우회할 수 있다.
    """
    try:
        return await service.parse_intent(payload.text, today=date.today())
    except (llm.LlmNotConfigured, llm.LlmUnavailable) as exc:
        raise _UNAVAILABLE from exc
