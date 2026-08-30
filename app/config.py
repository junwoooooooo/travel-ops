from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """설정은 .env에서만 온다. 값이 비면 import 시점에 죽는다(fail fast)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

    # 비밀이 아니라 배포 표식이다. 이미지 빌드 인자로 주입되고, 로컬·테스트에서는 unknown이다.
    # 기본값이 있어야 하는 이유: 없으면 .env 없는 환경에서 앱이 import 시점에 죽는다
    git_sha: str = "unknown"


settings = Settings()
