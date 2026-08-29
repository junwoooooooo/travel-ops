# Travel Ops

여행 운영 시스템 — Plan/Execute/Operate. FastAPI + LangGraph + Celery + PostgreSQL.

## 작업 방식
- 작업 전 ROADMAP.md의 "현재 세션"(첫 미체크 항목)만 읽고, 그 세션 범위만 진행
- 세션 완료 조건: DoD 확인 + pytest 통과 + 커밋. 완료 시 ROADMAP.md 체크박스 갱신
- 새 아이디어는 구현하지 말고 ROADMAP.md 6장 백로그에 추가 제안만
- 큰 세션은 코드 작성 전에 계획을 먼저 보여주고 승인받기
- 세션 작업은 `feat/session-N-이름` 브랜치에서 진행. 세션 완료 시 push + `gh pr create --fill`까지 자동 수행
- 머지는 사용자가 "머지해"라고 지시했을 때만 `gh pr merge --squash --delete-branch`로 수행
- main 직접 push 금지, force push 금지

## 명령어
- 개발: docker compose up postgres redis + uvicorn app.main:app --reload
- 테스트: pytest / 풀도커 점검: docker compose up --build

## 절대 규칙
- 도메인 간 접근은 상대 service 함수로만 (남의 models 직접 접근 금지)
- 비밀값은 .env만. 코드·커밋·로그에 금지. .env.example 최신 유지
- 라이브러리 추가 시 requirements.txt에 == 버전 고정
- 소유권 위반 응답은 404 (존재 노출 금지)
- 설계 변경 시 docs/adr/에 기록, 근거는 ROADMAP.md 1장의 R1~R5를 가리킬 것
