from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """설정은 .env에서만 온다. 값이 비면 import 시점에 죽는다(fail fast)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30


settings = Settings()
