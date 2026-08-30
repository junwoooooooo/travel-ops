# 로컬 Python과 같은 라인 (ADR-0001)
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /srv

# 코드보다 먼저 복사한다 — requirements가 그대로면 아래 install 레이어는 캐시된다
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
# 배포된 컨테이너 안에서 `alembic upgrade head`를 돌린다. 이미지에 없으면 스키마를 못 올린다 (ADR-0007)
COPY alembic.ini .
COPY migrations ./migrations

# 배포된 커밋 표식. 반드시 COPY 뒤에 둔다 — 앞에 두면 커밋마다 pip install 레이어가 깨진다
ARG GIT_SHA=unknown
ENV GIT_SHA=${GIT_SHA}

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
