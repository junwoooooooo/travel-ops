# ADR-0003: 비밀번호 해싱은 pwdlib + Argon2id

- 상태: 채택
- 날짜: 2026-08-29

## 상황
auth 도메인에 비밀번호 저장이 필요하다. 저장된 해시는 나중에 바꾸기 어려우므로(전 사용자 재설정 또는 이중 검증 코드 필요) 세션 2에서 확정해야 한다.

## 후보
1. passlib + bcrypt — 국내 튜토리얼·기존 코드베이스의 사실상 표준
2. pwdlib + Argon2id — FastAPI 공식 문서의 현행 권장
3. bcrypt 라이브러리 직접 호출

## 결정과 근거
pwdlib + Argon2id.
- Argon2id는 OWASP Password Storage 1순위 권장. 메모리 하드라 GPU 병렬 공격에 bcrypt보다 강하다
- passlib 1.7.4는 유지보수가 멈춰 있고 bcrypt 4.1+ 에서 `__about__` 관련 경고를 뱉는다. 운영 인력 0명이므로 기동 로그에 상시 경고가 끼는 상태를 만들지 않는다 (R3)
- pwdlib은 해시 스킴 교체 경로(`PasswordHash`에 hasher 추가)를 내장해, 나중에 알고리즘을 바꿔도 재로그인 시 자동 재해싱이 가능하다
- 면접에서 "왜 bcrypt가 아닌가"를 근거와 함께 답할 수 있다 (R5)

## 뒤집는 조건
Argon2 메모리 비용(기본 64MB/해시)이 프리티어 EC2 메모리와 충돌하면 파라미터를 낮추고, 그래도 안 되면 bcrypt로 복귀한다.
