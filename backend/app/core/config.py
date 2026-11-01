from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "CYVANTA"
    app_version: str = "0.1.0"
    app_env: str = "development"

    secret_key: str
    access_token_expire_minutes: int = 30

    database_url: str = "sqlite:///./cyvanta.db"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()
