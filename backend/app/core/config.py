import logging
from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

# Environments allowed to run with development defaults. Anything else —
# including a misspelled or never-set ENVIRONMENT — must satisfy the
# production-grade checks, so they fail CLOSED instead of being skipped.
_DEV_ENVIRONMENTS = frozenset({"local", "test"})

_INSECURE_JWT_SECRETS = frozenset({"", "change-me", "changeme", "secret", "test"})
_INSECURE_SERVICE_TOKENS = frozenset({"", "change-me", "change-me-too"})


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_ignore_empty=True, extra="ignore")

    # runtime
    #
    # Defaults to "production" — the SECURE direction. It used to default to
    # "local", which meant an UNSET or empty ENVIRONMENT silently selected the
    # development branch and skipped every check below. (Review G-05: a test
    # that passed `environment=""` as a constructor argument did not cover that,
    # because an unset variable yields the default, not an empty string.)
    #
    # Local development sets ENVIRONMENT=local explicitly — see .env.example and
    # the CI job env. A deploy that forgets the variable now fails closed rather
    # than running unvalidated.
    environment: str = "production"
    debug: bool = True

    # data stores
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/sales"
    # §58: Supavisor pooler port is 6543 (5432 is the direct/admin port).
    # The pooler URL is used by the app runtime; admin/migrations use 5432.
    database_url_pooler: str = "postgresql+asyncpg://postgres:postgres@localhost:6543/sales"
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
    # Webchat visitor sessions are long-lived by nature (a returning visitor
    # keeps the same conversation) but are still server-signed (S2).
    webchat_session_ttl_seconds: int = 60 * 60 * 24 * 30

    # event bus / workers
    stream_maxlen: int = 100_000
    consumer_block_ms: int = 5_000
    worker_max_attempts: int = 5
    worker_backoff_base_seconds: float = 2.0

    # AI providers (OpenAI-compatible endpoints; per-tenant overrides via
    # model_configs table take precedence over these defaults)
    ai_provider_primary: str = ""
    ai_api_key_primary: str = ""
    ai_base_url_primary: str = ""

    # §42: the monthly AI spend cap (USD) applied when a tenant has no
    # BudgetPolicy row. Configurable so an operator can change the ceiling
    # without a deploy; the default preserves the previous hard-coded constant.
    ai_monthly_budget_cap_default: float = 50.0

    # Circuit breaker (§47) applied to every external dependency — AI provider,
    # WhatsApp/Telegram, object storage. Tunable so an operator can loosen the
    # threshold without a deploy; the defaults match CircuitBreaker's own.
    circuit_breaker_failure_threshold: int = 5
    circuit_breaker_recovery_seconds: float = 30.0
    circuit_breaker_half_open_successes: int = 2

    # channels
    whatsapp_app_secret: str = ""
    whatsapp_verify_token: str = ""
    telegram_webhook_secret: str = ""
    messenger_app_secret: str = ""
    messenger_verify_token: str = ""
    instagram_app_secret: str = ""
    instagram_verify_token: str = ""

    # object storage
    s3_endpoint: str = ""
    s3_region: str = ""
    s3_bucket: str = ""
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""

    # outbox relay
    outbox_poll_interval_seconds: float = 0.5
    outbox_batch_size: int = 100

    # CORS: comma-separated origins, "*" allows all (dev); set explicitly in prod
    cors_origins: str = "*"

    # n8n adapter
    n8n_base_url: str = ""

    # internal service auth (n8n -> core)
    service_token_internal: str = "change-me-too"

    @property
    def is_secure_environment(self) -> bool:
        """True when this deployment must satisfy the production-grade checks.

        Several security behaviours key off `environment` — the OpenAPI schema
        is exposed when it is not "production" (main.py), HSTS is only sent for
        "production" (middleware.py), and the rate limiter is disabled for
        "test". So an unrecognised value must be treated as secure-required.
        """
        return self.environment not in _DEV_ENVIRONMENTS

    @model_validator(mode="after")
    def _refuse_insecure_configuration(self) -> "Settings":
        """Fail fast (H2, review G-05): refuse insecure settings outside local/test.

        This used to run only when `environment == "production"`, but
        `environment` DEFAULTS to "local". A deploy that forgot to set
        ENVIRONMENT — or misspelled it "prod" — therefore validated nothing and
        would run with the publicly-known default JWT secret while serving the
        OpenAPI schema. Staging was unvalidated too, which defeats the point of
        having a staging environment.

        Inverted so an unrecognised environment fails CLOSED. Production already
        satisfies every one of these checks (it boots today with the stricter
        production branch), so this only adds enforcement where it was missing.
        """
        if not self.is_secure_environment:
            return self

        where = f"in environment {self.environment!r}"
        if self.jwt_secret in _INSECURE_JWT_SECRETS:
            raise ValueError(f"JWT_SECRET must be set {where}")
        # PyJWT warns below 32 bytes for HS256; a short key is brute-forceable
        # offline from a single captured token, so refuse rather than warn.
        if len(self.jwt_secret.encode()) < 32:
            raise ValueError(f"JWT_SECRET must be at least 32 bytes {where}")
        if self.service_token_internal in _INSECURE_SERVICE_TOKENS:
            raise ValueError(f"SERVICE_TOKEN_INTERNAL must be set {where}")
        if self.cors_origins.strip() == "*":
            raise ValueError(f"CORS_ORIGINS must not be * {where}")

        # DEBUG is NOT a hard failure: it only controls the log level, and
        # refusing to boot over log verbosity would take a running deployment
        # down for a cosmetic problem. It is logged loudly instead.
        if self.debug:
            logger.warning(
                "config.debug_enabled_in_secure_environment environment=%s — "
                "set DEBUG=false",
                self.environment,
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
