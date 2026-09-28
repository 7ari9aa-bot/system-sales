import base64
import binascii
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
_INSECURE_MASTER_KEYS = frozenset({"", "change-me", "change-me-too", "secret", "test"})


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
    # Connection-pool sizing. The worker process holds TWO connections per
    # in-flight event (the §127 claim transaction stays open across the whole
    # effect, and every handler opens its own session — GAP_REGISTER's measured
    # arithmetic), so the pool must cover 2 x (pools + relay) + headroom or the
    # fleet times out at 30 s with no database error anywhere. The invariant is
    # pinned by tests/test_db_pool_invariant.py; overriding these in a deploy
    # must keep it true.
    db_pool_size: int = 12
    db_max_overflow: int = 10
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

    # §36: USD per minute of audio for inbound voice transcription. Whisper is
    # billed per minute, so this is what the budget gate reserves before the
    # provider call. Operator-tunable for the same reason as the cap above.
    ai_stt_cost_per_minute: float = 0.01

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
    # Supabase Storage S3-compatible credentials are server-side only. Private
    # media is returned through short-lived presigned GET URLs.
    s3_signed_url_ttl_seconds: int = 900

    # outbox relay
    outbox_poll_interval_seconds: float = 0.5
    outbox_batch_size: int = 100
    # G-08: how long an outbox row may sit in 'publishing' before another relay
    # re-queues it. Claim → publish → mark now run in ONE transaction, so a
    # live relay always holds the row's Postgres lock and the reclaim skips it
    # at any age; this lease is the backstop for a row that was durably
    # committed in 'publishing' by something else (an older deployment
    # mid-roll, ops SQL), never the primary guarantee.
    outbox_lease_seconds: float = 300.0
    # Cool-down before a 'failed' row (bus unreachable at publish time) is
    # re-queued, so a Redis outage retries on its own instead of stranding.
    outbox_failed_requeue_seconds: float = 300.0

    # CORS: comma-separated origins, "*" allows all (dev); set explicitly in prod
    cors_origins: str = "*"

    # Internal service credential used by trusted metrics scrapers.
    service_token_internal: str = "change-me-too"

    # §68: at-rest envelope encryption of Integration.credentials
    # (app.core.secrets.EnvelopeSecretStore). Base64-encoded; must decode to
    # at least 32 bytes. Empty is tolerated ONLY in local/test, where a
    # published dev-only key is used (loudly logged); secure environments
    # refuse to boot without it.
    secrets_master_key: str = ""
    # Comma-separated OLD master keys, kept for decryption only during a
    # rotation grace period (§69: existing rows must not break at switch-over).
    secrets_previous_master_keys: str = ""

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
        if self.secrets_master_key in _INSECURE_MASTER_KEYS:
            raise ValueError(f"SECRETS_MASTER_KEY must be set {where}")
        # The master key protects every integration credential at rest; a
        # short or non-base64 key would weaken AES-256-GCM to brute-forceable.
        try:
            decoded_master = base64.b64decode(self.secrets_master_key, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError(f"SECRETS_MASTER_KEY must be base64 {where}") from exc
        if len(decoded_master) < 32:
            raise ValueError(
                f"SECRETS_MASTER_KEY must decode to at least 32 bytes {where}"
            )
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
