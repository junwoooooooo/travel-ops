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

`--reload`은 콘솔이 붙은 터미널에서 실행해야 한다. 백그라운드·출력 리다이렉트로 띄우면 Windows에서
재기동 신호(CTRL_C_EVENT)가 전달되지 않아 변경 감지 후 그대로 멈춘다.

접속은 두 모드 모두 http://localhost:8000/docs.
`.env`의 `DATABASE_URL`은 하이브리드 기준(`@localhost`)이고, 컨테이너 안에서 쓰는 `@postgres` 주소는
`docker-compose.yml`의 `api.environment`가 덮어쓴다. 두 모드를 동시에 띄우면 8000 포트가 충돌한다.
