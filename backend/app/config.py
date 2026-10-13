from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="APP_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://pharmacy:pharmacy@localhost:5432/pharmacy"
    # Allowed clock skew between a client and the server when rejecting
    # dispenses that claim to have happened in the future.
    future_dispense_tolerance_seconds: int = 300
    default_page_size: int = 20
    max_page_size: int = 100
    cors_origins: list[str] = ["http://localhost:4200", "http://localhost:8080"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
