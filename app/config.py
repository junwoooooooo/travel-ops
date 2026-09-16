from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """설정은 .env에서만 온다. 값이 비면 import 시점에 죽는다(fail fast)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

    # 아래 둘은 기본값이 있다 — fail fast 원칙의 의도적 예외다.
    # CD는 서버의 .env를 고치지 않는다. 필수 필드로 두면 이 값들이 서버 .env에 들어가기 전에
    # 머지되는 순간 EC2의 앱이 import에서 죽는다. git_sha가 이미 같은 이유로 기본값을 갖는다.
    # 하이브리드 개발(호스트 uvicorn → 도커 redis) 기준이라 localhost다 (ADR-0005 패턴).
    redis_url: str = "redis://localhost:6379/0"
    # 빈 값이어도 앱은 뜬다. 실패는 카카오를 실제로 부르는 지점에서 KakaoNotConfigured로 난다 —
    # 키가 없다고 로그인·여행 조회까지 멈출 이유가 없다 (ADR-0010)
    kakao_rest_api_key: str = ""
    # 카카오 키와 같은 규칙이다 — 빈 값이어도 앱은 뜨고, LLM을 부르는 지점에서
    # LlmNotConfigured로 실패한다 (ADR-0011)
    openai_api_key: str = ""
    # 파싱 품질이 뒤 단계(research·draft) 전부를 좌우하는데 호출은 요청당 1회·짧은 문장이라
    # 비용이 미미하다. 저가 모델로 내리는 것은 ROADMAP 6장 "여유 시 추가"의 모델 라우터 몫이고,
    # 그때 코드가 아니라 이 환경변수만 바꾸면 된다
    openai_model: str = "gpt-5.5"

    # 비밀이 아니라 배포 표식이다. 이미지 빌드 인자로 주입되고, 로컬·테스트에서는 unknown이다.
    # 기본값이 있어야 하는 이유: 없으면 .env 없는 환경에서 앱이 import 시점에 죽는다
    git_sha: str = "unknown"


settings = Settings()
