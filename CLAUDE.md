# Travel Ops

여행 운영 시스템 — Plan/Execute/Operate.
현재 스택: FastAPI + SQLAlchemy/Alembic + PostgreSQL + Redis(캐시) + OpenAI(파싱).
아직 없음: LangGraph는 세션 13, Celery는 Phase 5 — 있다고 전제하지 말 것.

## 구조
- `app/` — `auth`(User) / `trips`(Trip, Block) / `planning`(테이블 없음) / `integrations`(http, kakao, weather) / `core`(db, cache, security, llm)
- **blocks는 별도 도메인이 아니다** — `app/trips/` 안의 두 번째 테이블. `app/blocks/`를 만들지 말 것 (ADR-0009)
- LLM은 `core/llm.py`로만 부른다. 도메인은 SDK를 모른다 — 프롬프트와 판단은 `planning/service.py` (ADR-0011)
- **LLM에게 "충분한가"를 묻지 말 것.** LLM은 추출만, 판정은 코드가 (ADR-0007·0011)
- 마이그레이션은 `migrations/`, ERD는 `docs/erd.md`, 설계 근거는 `docs/adr/`

## 작업 방식
- 작업 전 ROADMAP.md의 "현재 세션"(첫 미체크 항목)만 읽고, 그 세션 범위만 진행
- 세션 완료 조건: DoD 확인 + pytest 통과 + 커밋. 완료 시 ROADMAP.md 체크박스 갱신
- 새 아이디어는 구현하지 말고 ROADMAP.md 6장 백로그에 추가 제안만
- 큰 세션은 코드 작성 전에 계획을 먼저 보여주고 승인받기
- 세션 작업은 `feat/session-N-이름` 브랜치에서 진행. 세션 완료 시 push + PR 생성까지 자동 수행
- PR 생성은 `gh pr create --fill --title "feat: 세션 N — 이름"` — `--title`을 항상 명시
  (`--fill`만 쓰면 커밋이 여러 개일 때 제목이 브랜치명으로 떨어진다. 사후 보정 대신 생성 시 확정)
- 머지는 사용자가 "머지해"라고 지시했을 때만 `gh pr merge --squash --delete-branch`로 수행
- main 직접 push 금지, force push 금지

## 명령어
- 개발: `docker compose up -d postgres redis` → `alembic upgrade head` → `.\venv\Scripts\python.exe -m uvicorn app.main:app --reload`
- 스키마 변경: 모델 수정 → `alembic revision --autogenerate -m "..."` → 생성된 파일 검토 → `alembic upgrade head`
- 테스트: `.\venv\Scripts\python.exe -m pytest` — **postgres가 떠 있어야 한다**(conftest가 `travelops_test`를 생성). cache·integrations 테스트는 redis도 필요
- 풀도커 점검: `docker compose up --build`
- 명령어 전체·배포 절차는 README.md가 정본. 여기는 요약이다

## 절대 규칙
- 도메인 간 접근은 상대 service 함수로만 (남의 models 직접 접근 금지)
- 비밀값은 .env만. 코드·커밋·로그에 금지. .env.example 최신 유지
- 라이브러리 추가 시 requirements.txt에 == 버전 고정
- 소유권 위반 응답은 404 (존재 노출 금지). 업스트림(LLM·외부 API) 장애는 503
- 프롬프트 원문·사용자 문장은 로그에 남기지 말 것 (개인정보)
- 스키마는 마이그레이션으로만 변경 (create_all 금지). 모델을 고쳤으면 리비전도 같은 커밋에 (ADR-0007)
- 설계 변경 시 docs/adr/에 기록, 근거는 ROADMAP.md 1장의 R1~R5를 가리킬 것
