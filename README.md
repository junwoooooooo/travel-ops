# travel-ops
일정 생성에서 멈추지 않는 여행 운영 시스템

## 로컬 개발

**하이브리드 (평소)** — DB·Redis만 도커, 앱은 호스트에서 핫리로드
```powershell
docker compose up -d postgres redis
python -m venv venv            # 최초 1회
.\venv\Scripts\python.exe -m pip install -r requirements.txt   # 최초 1회
.\venv\Scripts\Activate.ps1
alembic upgrade head           # 스키마를 최신으로 (마이그레이션이 추가됐을 때마다)
uvicorn app.main:app --reload
```

앱은 더 이상 테이블을 만들지 않는다. 스키마는 `alembic upgrade head`로만 생긴다 (ADR-0007).
모델을 고쳤으면 `alembic revision --autogenerate -m "..."`으로 리비전을 만들고 파일을 눈으로
검토한 뒤 커밋한다. 잊으면 `tests/test_migrations.py`가 CI에서 잡는다.

**풀도커 (배포 리허설)** — 세션 6 EC2 배포와 같은 경로
```powershell
docker compose run --rm api alembic upgrade head
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
docker compose -f docker-compose.prod.yml build
docker compose -f docker-compose.prod.yml run --rm api alembic upgrade head
docker compose -f docker-compose.prod.yml up -d
```

DB 위치는 이 파일이 아니라 서버 `.env`의 `DATABASE_URL`이 정한다 (ADR-0005).

```bash
# RDS를 쓰는 동안        → DATABASE_URL=...@<RDS 엔드포인트>:5432/travelops
# RDS를 지운 뒤          → DATABASE_URL=...@postgres:5432/travelops 로 바꾸고
docker compose -f docker-compose.prod.yml --profile localdb up -d
```

## 자동 배포 (CD)

main에 push하면 `.github/workflows/ci.yml`의 `deploy` job이 돈다. `test`가 통과해야만 시작하고,
PR에서는 돌지 않는다.

1. secret의 배포 키로 EC2에 ssh
2. 서버에서 `git reset --hard <그 커밋의 SHA>` — `pull`이 아니라 SHA 고정이다 (ADR-0006)
3. `build` → **`alembic upgrade head`** → `up -d` + dangling 이미지 정리.
   마이그레이션을 앱 기동에 숨기지 않고 별도 단계로 두면, 실패했을 때 alembic 에러가
   Actions 로그에 그대로 뜬다 (ADR-0007)
4. 러너가 **바깥에서** `http://<EC2_HOST>/health`를 3초 간격 20회 폴링.
   응답의 `commit`이 **이번 커밋과 같아야** 통과

4번이 없으면 "ssh가 안 끊겼다"를 "배포 성공"으로 읽는다. 그렇다고 200만 보는 것도 부족하다 —
아직 교체되지 않은 구 컨테이너도 200을 준다. `commit` 대조는 새 이미지가 뜬 뒤에만 참이 된다.

```bash
curl http://<EC2_HOST>/health
# {"status":"ok","commit":"a25df0f..."}   ← 지금 떠 있는 커밋
```

`commit`은 이미지 빌드 인자 `GIT_SHA`로 굽는다(Dockerfile의 `COPY app` 뒤 — 앞에 두면 커밋마다
pip install 레이어가 깨진다). 손으로 띄우면 `unknown`이다.

**필요한 설정** (GitHub → Settings → Secrets and variables → Actions)

| 종류 | 이름 | 값 |
|------|------|-----|
| Secret | `EC2_HOST` | EC2 퍼블릭 IP |
| Secret | `EC2_SSH_KEY` | 배포 전용 **개인키 전문** (`-----BEGIN`부터 마지막 줄까지) |
| Variable (선택) | `EC2_USER` | 기본값 `ubuntu`. Amazon Linux면 `ec2-user` |

전제: 서버 `~/travel-ops`가 git clone 상태 / 서버 `.env` 존재 / 보안그룹 22·80 개방.

배포 키는 로컬 접속용 `.pem`과 **따로** 만든다. 유출됐을 때 이 키만 회수할 수 있어야 한다.

```powershell
# 암호는 빈 값(엔터 두 번) — Actions는 암호를 타이핑할 수 없다
ssh-keygen -t ed25519 -C "github-actions@travel-ops" -f "$env:USERPROFILE\.ssh\travel_ops_deploy"
```

공개키(`.pub`)를 서버 `~/.ssh/authorized_keys`에 추가하고, 개인키를 `EC2_SSH_KEY`에 넣는다.
인스턴스를 재생성하면 `EC2_HOST`와 서버의 `authorized_keys`를 다시 세팅해야 한다.
