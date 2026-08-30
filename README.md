# travel-ops
일정 생성에서 멈추지 않는 여행 운영 시스템

## 로컬 개발

**하이브리드 (평소)** — DB·Redis만 도커, 앱은 호스트에서 핫리로드
```powershell
docker compose up -d postgres redis
python -m venv venv            # 최초 1회
.\venv\Scripts\python.exe -m pip install -r requirements.txt   # 최초 1회
.\venv\Scripts\Activate.ps1
uvicorn app.main:app --reload
```

**풀도커 (배포 리허설)** — 세션 6 EC2 배포와 같은 경로
```powershell
docker compose up --build
```

## 테스트

```powershell
docker compose up -d postgres          # 테스트도 이 DB를 쓴다
.\venv\Scripts\python.exe -m pytest
```

개발 DB(`travelops`)는 건드리지 않는다. `tests/conftest.py`가 `travelops_test`를 따로 만들어
테스트마다 테이블을 새로 파고 지운다. CI도 같은 코드가 그대로 돈다.

`--reload`은 콘솔이 붙은 터미널에서 실행해야 한다. 백그라운드·출력 리다이렉트로 띄우면 Windows에서
재기동 신호(CTRL_C_EVENT)가 전달되지 않아 변경 감지 후 그대로 멈춘다.

접속은 두 모드 모두 http://localhost:8000/docs.
풀도커에서는 Nginx도 함께 떠서 http://localhost (80번)로도 같은 앱에 닿는다 — 서버와 같은 경로다.
`.env`의 `DATABASE_URL`은 하이브리드 기준(`@localhost`)이고, 컨테이너 안에서 쓰는 `@postgres` 주소는
`docker-compose.yml`의 `api.environment`가 덮어쓴다. 두 모드를 동시에 띄우면 8000 포트가 충돌한다.

## 배포 (EC2)

서버는 `docker-compose.prod.yml`만 쓴다. 로컬 파일과 달리 api를 호스트에 공개하지 않고,
바깥을 보는 것은 Nginx(80)뿐이다.

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

DB 위치는 이 파일이 아니라 서버 `.env`의 `DATABASE_URL`이 정한다 (ADR-0005).

```bash
# RDS를 쓰는 동안        → DATABASE_URL=...@<RDS 엔드포인트>:5432/travelops
# RDS를 지운 뒤          → DATABASE_URL=...@postgres:5432/travelops 로 바꾸고
docker compose -f docker-compose.prod.yml --profile localdb up -d
```
