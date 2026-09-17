from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_ignore_empty=True, extra="ignore")

    # runtime
    environment: str = "local"  # local | staging | production
    debug: bool = True

    # data stores
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/sales"
    # Direct/admin URL used by migrations and maintenance scripts (bypasses pgbouncer).
    database_url_admin: str = ""
    # App runtime role (sales_app, no bypassrls — RLS applies to it). Written by
    # scripts/provision.py; API and workers should use this, not postgres.
    database_url_app: str = ""
    database_url_app_admin: str = ""
    sales_app_db_password: str = ""
    redis_url: str = "redis://localhost:6379/0"

    # auth
    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    access_token_ttl_seconds: int = 60 * 30
    refresh_token_ttl_seconds: int = 60 * 60 * 24 * 14

    # event bus / workers
    stream_maxlen: int = 100_000
    consumer_block_ms: int = 5_000
    worker_max_attempts: int = 5
    worker_backoff_base_seconds: float = 2.0

    # channels
    whatsapp_app_secret: str = ""
    whatsapp_verify_token: str = ""
    telegram_webhook_secret: str = ""

    # object storage
    s3_endpoint: str = ""
    s3_region: str = ""
    s3_bucket: str = ""
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""

    # outbox relay
    outbox_poll_interval_seconds: float = 0.5
    outbox_batch_size: int = 100

    # internal service auth (n8n -> core)
    service_token_internal: str = "change-me-too"


@lru_cache
def get_settings() -> Settings:
    return Settings()
