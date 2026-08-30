# ADR-0008: 도메인의 공개 API는 service다

- 상태: 채택
- 날짜: 2026-08-30

## 상황
trips 라우터는 "지금 로그인한 사람"이 필요하다. 그 의존성(`get_current_user`)은 세션 2에서
`app/auth/router.py`에 만들어 두었다. 그대로 쓰면 **도메인 라우터가 남의 도메인 라우터를
import**하게 된다. 도메인이 늘어날수록(planning, monitoring, notifications) 같은 화살표가
계속 늘어난다.

CLAUDE.md의 절대 규칙은 "도메인 간 접근은 상대 service 함수로만"이다.

## 후보
1. `app.auth.router`에서 `CurrentUser`를 import한다 (FastAPI 프로젝트에서 흔한 모양)
2. `get_current_user`를 `app/auth/service.py`로 내리고, auth·trips가 함께 그 파일을 본다
3. 도메인마다 `deps.py`를 추가한다 (4파일 문법이 5파일이 된다)

## 결정과 근거
**2번.**

- 규칙에 예외를 만들지 않는다. "남의 도메인은 service만 본다"가 문장이 아니라 실제 import
  그래프가 된다 — 새 도메인이 들어올 때 어디를 봐야 하는지 고민할 것이 없다
- 3번은 파일 문법을 늘린다. 파일 하나가 늘면 도메인 5개에서 5개가 는다(R3)
- 대가: `auth/service.py`가 FastAPI를 안다(`Depends`, `OAuth2PasswordBearer`). service를
  "순수 함수"로 유지하려던 취향과는 어긋나지만, 이 계층은 어차피 DB 세션을 받는다.
  프레임워크 비종속이 필요한 곳은 LangGraph 노드 로직이고(ROADMAP 8장 규칙 9), 거기는
  이 결정의 영향을 받지 않는다
- `DbSession` 별칭은 도메인 것이 아니라 설비이므로 `app/core/db.py`로 옮겼다. 도메인마다
  같은 줄을 복사하지 않는다

이동의 검증은 기존 `tests/test_auth.py`가 **한 글자도 안 고치고** 통과하는 것이다. 경로·응답·
상태코드가 그대로면 이건 리팩터링이고, 아니면 기능 변경이다.

## 뒤집는 조건
service가 FastAPI 없이 호출되어야 하는 곳이 생기면(예: Celery 워커가 인증 로직을 재사용),
순수 함수와 FastAPI 의존성 껍데기를 분리한다.
