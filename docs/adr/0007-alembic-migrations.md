# ADR-0007: 스키마 변경은 Alembic 마이그레이션으로만

- 상태: 채택
- 날짜: 2026-08-30

## 상황
Phase 0에서는 앱이 뜰 때 `Base.metadata.create_all`이 테이블을 만들었다. 주석에도 "Phase 0
한정 임시 조치"라고 적어 두었다. `create_all`은 **없는 테이블을 만들 뿐, 있는 테이블을 바꾸지
못한다.** 컬럼을 추가하거나 제약을 걸어도 조용히 무시되고, 배포된 DB만 코드보다 뒤처진다.

세션 8은 테이블이 둘이 되는 지점이다(users + trips). 앞으로 blocks·watches가 이어 붙고,
예산·시간처럼 틀리면 안 되는 제약이 스키마에 들어간다(R4). 스키마를 바꾸는 **수단**을 먼저
정하고 넘어가야 하는 시점이다.

## 후보
1. `create_all` 유지 — 신규 테이블만 만들고, 변경은 손으로 psql
2. SQL 파일을 직접 쓰고 순서대로 실행하는 자작 러너
3. Alembic

## 결정과 채택 근거
**3번, Alembic.** SQLAlchemy와 같은 계보라 모델에서 초안을 뽑을 수 있고(`--autogenerate`),
적용 이력이 DB 안(`alembic_version`)에 남는다.

- 1번은 "조용한 실패"다. 운영 인력 0명(R3)에서 가장 비싼 종류의 실패다 — 배포는 성공했는데
  DB만 다른 상태가 되고, 그 사실이 몇 커밋 뒤 엉뚱한 에러로 드러난다
- 2번은 이력·롤백·순서 판정을 전부 직접 만들어야 한다. 10주 예산에서 이건 본질이 아니다(R3)
- 데이터에 정합성 제약을 거는 것이 이 프로젝트의 설계다(R4). 제약을 나중에 추가할 수 있어야
  그 설계가 실행 가능하다

### 딸린 결정 3개

**(1) 0001은 조건부 baseline이다.**
로컬 개발 DB와 배포된 서버 DB에는 `create_all`이 만든 `users`가 이미 있다. 0001이 조건 없이
`create_table`을 하면 첫 배포가 "relation users already exists"로 죽고, 사람이 SSH로 들어가
`alembic stamp`를 쳐야 한다 — Phase 0에서 세운 "push하면 반영된다"(DoD)가 깨진다. 그래서
0001만 `users` 존재를 확인하고 있으면 건너뛴다. **이력이 없던 DB를 이력에 편입시키는 이 한
번에만 정당한 예외**이고, 0002부터는 분기가 없다.

**(2) 서버에서는 앱 기동과 분리된 별도 단계로 돌린다.**
`docker compose build` → `run --rm api alembic upgrade head` → `up -d` 순서다. 엔트리포인트에
`alembic upgrade head && uvicorn`으로 숨기는 방법도 있지만, 그러면 마이그레이션 실패가
컨테이너 크래시 루프 → "60초 안에 /health가 이 커밋을 보고하지 않았다"라는 **원인과 무관한
메시지**로만 드러난다. 별도 단계면 alembic 에러가 Actions 로그에 그대로 뜬다.
ADR-0005에서 세운 것과 같은 기준이다 — 1인 운영에서 조용한 실패가 가장 비싸다(R3).

**(3) 테스트는 `create_all`을 유지하고, 드리프트 시험지 하나를 따로 둔다.**
`db_session` fixture는 함수 단위라 매 테스트 스키마를 새로 판다. 여기서 마이그레이션 전체를
재생하면 리비전이 쌓일수록 pytest가 선형으로 느려진다. 대신 `tests/test_migrations.py`가
빈 DB에 마이그레이션만으로 스키마를 세운 뒤 `alembic check`로 모델과 대조한다. "모델은
고쳤는데 마이그레이션을 안 만든" 사고는 이 한 개가 잡는다. 빠른 테스트와 실제 배포 경로 검증을
둘 다 갖는다.

### 부수 사항
`alembic.ini`는 ASCII 전용이다. Alembic이 ini를 `encoding="locale"`로 읽어서(`util/compat.py`)
한국어 주석이 Windows cp949 콘솔에서 `UnicodeDecodeError`를 낸다. 설명은 UTF-8로 안전하게
읽히는 `migrations/README`와 `migrations/env.py`에 둔다. 접속 주소도 ini가 아니라 `.env` →
`app/config.py` → `env.py`의 `get_url()`에서 온다 (비밀값은 .env만).

## 뒤집는 조건
- 마이그레이션이 수십 개로 쌓여 드리프트 테스트의 `upgrade head`가 눈에 띄게 느려지면,
  과거 리비전을 하나로 압축(squash)한다
- 무중단 배포가 필요해지면 "마이그레이션 → 재기동" 2단계로는 부족하다. 확장 후 축소
  (expand/contract) 방식으로 바꾸고, 이 문서를 다시 쓴다
