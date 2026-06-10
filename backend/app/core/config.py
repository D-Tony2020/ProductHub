from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PRODUCTHUB_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    database_url: str = "postgresql+psycopg://producthub:producthub_dev@127.0.0.1:5440/producthub"
    jwt_secret: str = "dev-only-secret-change-me-0123456789abcdef"  # ≥32 字节，生产必须替换
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 30
    refresh_token_days: int = 7
    default_currency: str = "USD"
    # 配置树最大深度：DAG 防环之外的纵深防御
    max_config_depth: int = 10


@lru_cache
def get_settings() -> Settings:
    return Settings()
