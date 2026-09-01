# ADR-0009: 블록은 trips가 보관하는 검증 시점 스냅샷이다

- 상태: 채택
- 날짜: 2026-09-01

## 상황
세션 8까지 `users` 1:N `trips`가 섰다. `trips`는 여행의 테두리(어디를·언제·얼마로)이고,
아직 없는 것은 내용물 — 일정 한 칸이다. ROADMAP 4장은 Phase 1에서 Block의 "필드 자리를
미리 판다"고 적어 두었다(place_id·priority·booking·alternates·verified_at·slack_min).

미리 파는 이유가 있다. 블록을 실제로 쓰기 시작하는 것은 세션 12~14의 planning 그래프다.
그때 없는 필드는 Phase 2에서 그래프 코드·파서·SSE 페이로드·테스트를 **다시 열어서**
채우게 된다. 컬럼 하나 추가하는 DDL은 PostgreSQL에서 거의 공짜지만, 2주 전에 쓴 생성
코드를 다시 여는 비용은 그렇지 않다.

그런데 "미리 판다"와 스코프 방어(ROADMAP 8장 규칙 6)는 서로 당긴다. 어디까지가 준비이고
어디부터가 조기 추상화인지 기준이 필요하다.

## 후보
Block을 어디에 어떤 모양으로 둘 것인가에 대해:
1. `app/blocks/` 새 도메인 4파일 + `places` 정규화 테이블 + `blocks.place_id` FK
2. `app/blocks/` 새 도메인 4파일 + place는 blocks에 평탄화
3. `app/trips/`의 두 번째 테이블 + place는 blocks에 평탄화

## 결정과 채택 근거
**3번.** 그리고 필드는 "지금 안 파면 나중에 **백필이 불가능한** 값"만 미리 판다.

기준을 한 줄로: **DDL 비용이 아니라 백필 비용과 작성자 비용으로 판단한다.** nullable 컬럼
추가는 PG 11+에서 즉시 끝나므로 "언젠가 쓴다"는 지금 팔 이유가 못 된다. 팔 이유는
그 값이 **생성 시점에만 알 수 있어서 나중에 만들어낼 수 없을 때**다. 예상 비용, 좌표,
카테고리, anchor/filler 판단, 예약 필요 여부, 대안 2곳 — 전부 플래너가 그 순간 내린
판단이라 사후에 재구성할 수 없다. 반대로 `place_source`는 전부 'kakao'로 채울 수 있어서
지금 팔 이유가 없다.

### 딸린 결정 7개

**(1) 새 도메인을 만들지 않는다.**
ROADMAP 4장 디렉토리 트리에 `blocks/`가 없다 — 도메인은 auth·trips·planning·monitoring·
notifications 다섯이고, Block은 그 목록이 아니라 "핵심 스키마" 절에 있다. 4파일 문법은
**도메인 단위 규칙이지 테이블 단위 규칙이 아니다**(`models.py`에 클래스가 둘인 것은 위반이
아니고, 파일이 다섯이 되는 것이 ADR-0008이 기각한 형태다). Block은 trip 없이 존재·조회·
인가가 불가능하고, URL도 `/trips/{id}/blocks`이며, 수명이 CASCADE로 trip에 묶인다.

실질 이득이 따라온다. `migrations/env.py`와 `tests/conftest.py`가 이미 `app.trips.models`를
import하므로 **`Base.metadata` 등록 줄이 하나도 늘지 않는다** — env.py에서 import를
빠뜨리면 autogenerate가 그 테이블을 drop 대상으로 읽는 함정이 하나 더 생기지 않는다는 뜻이다.
`app/main.py`도 무변경이다. 세션 9의 구조 변경은 결과적으로 리비전 파일 하나뿐이 된다 (R3).

*뒤집는 조건*: Phase 5의 이벤트 API 3종(완료/건너뜀/문닫음)이 블록 단위 라우트를 요구하고
`app/trips/service.py`가 눈에 띄게 부풀면 그때 `app/blocks/`로 분리한다. 테이블과
마이그레이션은 이미 있으므로 순수한 파일 이동이다.

**(2) place는 평탄화한다. `places` 테이블을 만들지 않는다.**
`blocks.place_*`는 마스터 데이터가 아니라 **계획을 세운 시점의 스냅샷**이다. "그때 이
장소를 이렇게 기록했다"가 이 컬럼들의 의미다. 정규화해서 `places` 한 행을 여러 블록이
가리키게 만들면, Phase 5의 D-1 재검증이 그 행을 갱신하는 순간 **블록이 무엇을 보고
만들어졌는지가 지워진다** — diff의 좌변이 사라진다. 정규화가 감시를 돕는 게 아니라 방해한다.

순서도 틀린다. `places`의 컬럼은 카카오 응답 모양이 정하는데 세션 9는 그 API를 한 번도
호출하지 않은 시점이다. 지금 만들면 세션 10~11에서 반드시 고쳐 마이그레이션을 두 번 쓴다.
게다가 `blocks.place_id → places.id` FK를 걸면 **장소가 아직 해석되지 않은 블록을 저장할
수 없어**, draft → 장소 해석 → 검증으로 이어지는 세션 12~14 그래프 흐름과 정면 충돌한다.

place_id를 `NOT NULL` + `length(place_id) > 0`으로 못 박은 것이 이 프로젝트의 환각 차단
계약이다. 그건 JSONB blob 안이 아니라 DB가 강제하는 컬럼이어야 한다 (R4).

*뒤집는 조건*: Phase 3에서 장소별 RAG 근거를 붙일 때. 근거는 블록이 아니라 장소에 붙는
성질이라 그때가 진짜 분기점이다. 그 마이그레이션은 파괴적이지 않다 —
`INSERT INTO places SELECT DISTINCT ... FROM blocks` 한 줄이고, `blocks.place_*`는
스냅샷으로 그대로 남긴다.

**(3) alternates는 JSONB 배열이다.**
Plan B는 사전 계산된 스냅샷이고 독립 조회·조인·집계 대상이 아니다. 별도 테이블이면 모든
블록 읽기에 조인이 붙는데, "현장 지연 0초"(ROADMAP 2장)의 요건은 한 행 읽고 끝이다.
`parent_block_id`로 자기참조 행을 만들면 더 나쁘다 — `WHERE trip_id = ?`가 대안까지 세서
일자별 비용 합계가 틀리고 압축 엔진이 대안을 filler로 오해한다. 막으려면 모든 쿼리에
`parent_block_id IS NULL`이라는 영구 세금이 붙고, 한 번 빠뜨리면 **조용히** 틀린 숫자가 나온다.

역할을 나눈다: 원소의 모양은 Pydantic `AlternatePlace`가, 통의 모양은
`CHECK (jsonb_typeof(alternates) = 'array')`가 본다. **개수 2는 정책이라 Pydantic에만
둔다** — Phase 2가 3곳으로 바꿔도 마이그레이션이 필요 없다.

모델에서 `MutableList.as_mutable(JSONB)`를 쓴다. 없으면 `alternates.append(...)`를
SQLAlchemy가 보지 못해 저장이 조용히 안 되는데, Phase 2의 Plan B 심기가 정확히 그 코드다.

**(4) 시각은 여행에 대한 상대 좌표다.** `day_index`(1-based) + `start_time` + `duration_min`.
절대 datetime이면 `trips.start_date`가 모든 행에 복제되고, 사용자가 `PATCH /trips/{id}`로
날짜를 하루 미루면 모든 블록이 조용히 어긋난다. 그 불변식은 다른 테이블을 참조해야 해서
CHECK로 표현할 수 없다. 시간대 문제도 따라온다 — 오사카 일정의 "09:00"은 현지 벽시계인데
UTC로 굳히면 Phase 2의 운영시간 검증이 몇 시간씩 틀린다. 그래서 `Time`(tz 없음)이고
`timetz`는 쓰지 않는다.

`day_index`는 1-based다. "2일차"가 곧 2여야 API·로그·프롬프트·사람 말 사이에 off-by-one이
상설로 끼지 않는다. 실제 날짜는 `trips.start_date + (day_index - 1)`로 계산한다.

끝 시각 대신 **길이**를 저장하는 이유 둘. 하나, `end_time > start_time` CHECK를 걸면 자정을
넘는 블록(23:00→01:00)을 영구히 금지하게 되는데 미식 여행에서 그건 실제로 나온다. 둘,
Phase 5 압축 엔진의 "40분 지연 → filler 탈락 → 이후 시각 재계산"이 `duration_min`·
`slack_min` 분 단위 정수 누산으로 끝난다. `end_time`은 `BlockRead`의 계산 필드로 내보내므로
API 표면은 달라지지 않는다.

*뒤집는 조건*: 자정을 넘는 블록과 다음 날 첫 블록의 겹침까지 판정해야 해지면 겹침 검사를
날짜 경계 너머로 확장한다(지금은 `day_index` 안에서만 본다).

**(5) 순서 컬럼과 UNIQUE를 두지 않는다.**
같은 날 겹침을 service가 거부하므로 `start_time`이 그날 안에서 유일해지고,
`ORDER BY day_index, start_time, id`가 전순서가 된다. `order_index`를 따로 두면 순서의
진실이 둘이 되고 서로 어긋날 수 있다. "한 사람이 두 곳에 동시에 있다"는 검증 실패가 아니라
자기모순 데이터라, 예산 초과·이동시간 부족처럼 사람이 판단할 여지가 있는 것(Phase 2
validate)과 성격이 다르다 (R4).

*의도적 비목표*: `day_index <= 여행 일수` 검증은 넣지 않았다. 여행 날짜가 나중에 줄어드는
경우까지 보면 반쪽짜리가 되고, 그건 Phase 2 validate 노드의 명시적 영역이다.

**(6) 값 목록은 네이티브 ENUM이 아니라 `String(16)` + CHECK다.**
결정타는 취향이 아니라 이 프로젝트가 세운 게이트와의 충돌이다. `alembic check`
(= `tests/test_migrations.py`)는 enum 값 변경을 감지하지 못한다 — ADR-0007이 Alembic을
고른 근거가 "1인 운영에서 조용한 실패가 가장 비싸다"인데, 네이티브 ENUM은 그 안전망을
정확히 우회하는 타입이다. `op.drop_table`이 타입을 남기는 것도 문제다.
`migrations/README`가 권하는 `alembic downgrade -1` → `upgrade head` 왕복이
"type already exists"로 죽고, `test_migrations.py`는 DB를 통째로 다시 만들어서 그걸 못 잡는다.
값 추가도 `ALTER TYPE ... ADD VALUE`로 추가한 값을 **같은 트랜잭션 안에서 쓸 수 없어**
"값 추가 + 백필"을 한 리비전에 담지 못한다.

CHECK는 `drop_constraint` + `create_check_constraint` 두 줄이고 완전히 트랜잭셔널하며,
`trips`의 `ck_trips_date_order`와 한 글자도 다르지 않은 패턴이다 (R3).

값 목록의 원본은 `schemas.py`의 Pydantic `Literal`이다(422와 OpenAPI enum이 따라온다).
DB CHECK는 최종 방어선이다 — `trips`가 파이썬 검증과 CHECK를 이중으로 둔 것과 같은 구도다.

**알아야 할 경계선(세션 9에서 직접 실험해 확인했다).** 이 버전의 alembic은
`checkconstraint_byname` 플러그인으로 **CHECK의 추가·삭제를 이름 기준으로 감지한다** —
마이그레이션 파일에서 CHECK 하나를 지우면 드리프트 테스트가 실제로 실패한다. 그런데
**이름이 같고 식만 바뀐 경우는 감지하지 못한다**: `day_index >= 1`을 `day_index >= 0`으로
완화해도 게이트는 초록불이었다. 즉 **제약을 빠뜨리는 사고는 잡히지만 제약을 조용히
완화하는 사고는 안 잡힌다.** 제약의 조건식을 고칠 때는 리비전을 손으로 쓰고 눈으로 검토한다.

**(7) 인가는 부모 여행 하나에만 있다. `blocks.user_id`를 두지 않는다.**
`user_id`를 블록에 복제하면 인가 사실의 진실이 둘이 된다. 둘이 어긋났을 때 —
블록은 trip A를 가리키는데 user B를 주장 — **어떤 CHECK로도 못 잡는다**(테이블 간 제약이
불가능하다). 정규화 논쟁이 아니라 보안 논쟁이다 (R4).

결정 (1) 덕에 문제 자체가 사라진다. `app/trips/router.py`의 기존 `OwnedTrip` 의존성을 그대로
쓰므로 도메인 간 통로가 필요 없고, 404 본문이 **같은 예외 객체**라 `/trips/{id}`의 404와
자동으로 동일해진다. 별도 도메인이었다면 `"Trip not found"` 문자열이 두 파일에서 갈릴 수
있었고, 갈리는 순간 존재 여부가 새어 나간다.

### API 표면: GET + PUT 전량 교체
블록의 작성자는 사용자가 아니라 플래너이고, 플래너는 일정을 한 칸씩이 아니라 통째로
내놓는다 — 한 칸씩 POST할 클라이언트가 존재하지 않는다. Phase 2의 "2일차만 바꿔줘"도 행
단위 PATCH가 아니라 날짜 단위 교체라 PUT이 직계 전신이고, `POST /trips/{id}/revise`가 같은
service 함수를 부르게 된다. 겹침 같은 집합 불변식이 전량 쓰기에서 한 곳에 모이는 것도
이득이다 — 행 단위 PATCH였다면 매번 하루 전체를 재검증해야 한다.

대가는 매 PUT마다 블록 id가 바뀌는 것이다. Phase 1에 id를 들고 있는 클라이언트가 없으므로
지금은 무해하다. *뒤집는 조건*: Phase 5 이벤트 API 3종이 안정적인 블록 id를 요구할 때
`PATCH /trips/{tid}/blocks/{bid}`를 추가한다.

### 지금 파지 않은 것과 각각의 트리거
| 항목 | 트리거 | 나중 비용 |
|---|---|---|
| `status`(완료/건너뜀/문닫음) | Phase 5. 이벤트 파이프라인·멱등성 설계 **뒤에** | 필드가 아니라 상태 기계다. 전이 규칙을 모르는 채 값 목록만 파면 틀린다. 진실은 이벤트 로그에 있고 `blocks.status`는 그 투영인데, 투영을 원본보다 먼저 만들 수 없다. `ADD COLUMN ... DEFAULT 'planned'`는 즉시·백필 손실 0 |
| `place_address`·`phone`·영업시간 | 세션 10~11에 kakao 응답을 실제로 본 뒤 | nullable 컬럼 추가. 백필은 API 재호출이라 기계적 |
| `place_source` | 장소 출처가 둘 이상이 되면 | 전부 'kakao'로 백필 가능 |
| `places` 테이블 | (2)의 뒤집는 조건 | additive |
| `trips.revision_count`·검증 배지 | Phase 2 | **blocks 소속이 아니다.** 부분 수정이 delete+insert면 블록에 붙은 카운터는 함께 사라져 refine 상한 3회가 리셋으로 무력화된다. 그 상한은 그래프 런타임 상태이고, 기록이 필요하면 trips나 Phase 4 관측성 테이블이다 |
| `trips.timezone` | Phase 5에 절대 시각이 필요해지면 | (4)의 상대 좌표 규약으로 대체된다 |
| `currency` | 해외 예산을 현지 통화로 다룰 때 | `trips.budget_total`도 원 단위 정수다 |

### 부수 사항
`blocks.trip_id`에 인덱스를 만들었다(`trips.user_id`와 같은 이유 — PostgreSQL은 FK 컬럼에
인덱스를 자동으로 만들지 않는다). ROADMAP Phase 2의 "인덱스 before/after 수치"는 이 때문에
"인덱스가 없는 상태"를 잴 수 없게 됐는데, 데이터를 쌓은 뒤 `DROP INDEX` → 측정 →
`CREATE INDEX`로 재면 오히려 더 정직한 수치가 나온다. ROADMAP 해당 줄에 메모해 두었다.

좌표는 `Numeric`이 아니라 `Double`이다. 돈은 합계가 틀어지면 안 되지만(그래서 `cost`는
원 단위 정수다) 좌표는 1e-9도 안에서 정확하면 되는 측정값이고, JSONB로 들어가는
`alternates`와 같은 모양이어야 한다.

## 뒤집는 조건
- 위 각 결정의 뒤집는 조건이 개별로 적혀 있다
- 테이블이 늘어 제약 이름 규칙이 흔들리기 시작하면 `Base.metadata`에 `naming_convention`을
  도입한다. 비용이 테이블 수에 선형으로 늘므로 Phase 5(watches·events) 직전이 마지노선이다
