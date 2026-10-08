import base64
import binascii
import logging
from functools import lru_cache
from urllib.parse import urlsplit

from pydantic import Field, model_validator
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
    # DEBUG defaults to the QUIET direction (it used to default True, so a
    # deploy that never set it ran verbose in production). Local development
    # sets DEBUG=true explicitly — see .env.example. Outside local/test a
    # lingering debug=true is logged loudly (not a hard failure: it only
    # controls log verbosity — see _refuse_insecure_configuration below).
    debug: bool = False

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
    # Canonical HTTPS origin used to register provider callbacks. Do not infer
    # it from an untrusted inbound Host header.
    api_public_base_url: str = ""

    # Account recovery email. Delivery stays disabled until the operator has
    # verified a sending domain and configured these server-only values.
    resend_api_key: str = ""
    email_from: str = ""
    frontend_public_url: str = ""
    email_delivery_enabled: bool = False
    # Soft-launch escape hatch: a secure-environment deployment may boot with
    # email delivery OFF (password-reset-by-email then degrades — the reset
    # endpoint's anti-enumeration 202 still holds) ONLY when this opt-out is
    # EXPLICIT. Default True: the hard requirement the recovery wave shipped.
    email_delivery_strict: bool = True

    # auth
    jwt_secret: str = "change-me"
    # Pinned to HS256 (security.py defines the same constant and BOTH encode
    # and decode use it): the previous split — encode honoring this setting,
    # decode hardcoding HS256 — minted tokens no decoder accepted the moment
    # an operator changed it. A non-HS256 value in a secure environment is
    # refused outright (see _refuse_insecure_configuration).
    jwt_algorithm: str = "HS256"
    # Zero-logout rotation: the secret the PREVIOUS deployment signed with.
    # Tokens carry a kid header (the current secret's fingerprint) and
    # decode_token verifies against current or previous — so a secret roll
    # invalidates nothing until the old tokens expire on their own. Empty
    # (the default) means no rotation is in progress.
    jwt_secret_previous: str = ""
    access_token_ttl_seconds: int = 60 * 30
    refresh_token_ttl_seconds: int = 60 * 60 * 24 * 14
    # HttpOnly cookie auth (the XSS-hardening wave). None means AUTO:
    # secure everywhere except ENVIRONMENT=local, whose dashboard runs on
    # plain http. Set AUTH_COOKIE_SECURE explicitly in staging/production if
    # the dashboard ever serves over http behind a trusted proxy.
    auth_cookie_secure: bool | None = None
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
    # §144: per-tenant in-flight cap. 0 (the default) DERIVES the gate from the
    # DB pool (pool_size + max_overflow): the old hard-coded 50 exceeded the
    # 12+10 pool, so a tenant that was admitted past the gate could still
    # starve on pool timeouts it thought were another tenant's fault. Set an
    # explicit TENANT_CONCURRENCY to override; the invariant
    # (gate <= pool capacity) still holds because 0-derivation is the default
    # and an explicit value is an operator decision. See tenancy.TenantConcurrencyGovernor.
    tenant_concurrency: int = 0
    worker_max_attempts: int = 5
    worker_backoff_base_seconds: float = 2.0

    # AI providers (OpenAI-compatible endpoints; per-tenant overrides via
    # model_configs table take precedence over these defaults)
    ai_provider_primary: str = ""
    # The model NAME is its own setting: `provider` identifies the API dialect
    # ("openai"), not a model. Reading this through getattr(..., "") let a
    # missing field degrade the request to `model="openai"`, and extra="ignore"
    # swallowed AI_MODEL_PRIMARY from the environment — a tenant with no
    # model_configs row then failed at the provider with an unattributable 400.
    ai_model_primary: str = ""
    ai_api_key_primary: str = ""
    ai_base_url_primary: str = ""

    # Customer Agent vision stack (§12): the multimodal embedding speaks
    # DashScope's native (non-OpenAI) schema and the reranker speaks Jina's.
    # tongyi-embedding-vision-flash emits fixed 768-dim vectors — verified
    # 2026-09-29; a model change invalidates every stored vector (§12.6).
    ai_embedding_vision_base_url: str = "https://dashscope-intl.aliyuncs.com/api/v1"
    ai_embedding_vision_api_key: str = ""
    ai_embedding_vision_model: str = "tongyi-embedding-vision-flash"
    ai_embedding_vision_dimensions: int = 768
    ai_reranker_base_url: str = "https://api.jina.ai/v1"
    ai_reranker_api_key: str = ""
    ai_reranker_model: str = "jina-reranker-m0"

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
    # Facebook Login for Business (the Meta OAuth connect flow): the dialog
    # authorizes the operator's pages, the callback exchanges the code and
    # stores the PAGE token as the channel credential. The redirect URI must
    # be registered verbatim in Meta → Valid OAuth Redirect URIs.
    meta_app_id: str = ""
    meta_app_secret: str = ""
    meta_oauth_redirect_uri: str = ""
    # Optional. Set ONLY for a Business-type app using Facebook Login for
    # Business: the dashboard configuration id replaces the scope list on the
    # login dialog (developers.facebook.com/docs/facebook-login/facebook-
    # login-for-business). Leave empty for classic Consumer-type apps.
    meta_oauth_config_id: str = ""
    messenger_app_secret: str = ""
    messenger_verify_token: str = ""
    instagram_app_secret: str = ""
    instagram_verify_token: str = ""
    # Email channel webhook (SendGrid bearer / Mailgun HMAC). Empty = the email
    # adapter cannot verify a delivery and rejects ALL of them (fail closed),
    # exactly like every other channel secret above.
    email_webhook_secret: str = ""

    # object storage
    s3_endpoint: str = ""
    s3_region: str = ""
    s3_bucket: str = ""
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    # Supabase Storage S3-compatible credentials are server-side only. Private
    # media is returned through short-lived presigned GET URLs.
    s3_signed_url_ttl_seconds: int = 900
    # Server-side Supabase Storage REST fallback. The service-role key is only
    # used by the API/workers; it must never be exposed to browser code.
    supabase_url: str = ""
    supabase_service_role_key: str = ""

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

    # How many reverse proxies sit between the internet and this process and
    # are trusted to APPEND their peer to X-Forwarded-For. The real client is
    # then the entry N hops from the RIGHT of the chain (middleware._client_ip):
    # everything further left is attacker-injectable. Default 1 covers a single
    # fronting proxy (Vercel / Cloudflare / Railway alone); behind a chain
    # (e.g. Cloudflare → Vercel → app) set 2 — taking the LAST entry there
    # keyed every user to the inner proxy's edge IP and mass-throttled them.
    trusted_proxy_count: int = 1

    # Internal service credential used by trusted metrics scrapers.
    service_token_internal: str = "change-me-too"

    # Website Platform integration (external presentation plane): per-tenant
    # keys for the catalog exposure endpoint. JSON of tenant_id -> key.
    # Example: WEBSITE_PLATFORM_TENANT_KEYS='{"<tenant-uuid>":"wpk-tenant-secret"}'
    website_platform_tenant_keys: dict[str, str] = Field(default_factory=dict)

    # Where the external Website Platform lives (API + Studio), used by the
    # website-builder integration module for SSO deep links.
    website_platform_api_url: str = "https://wp-platform-hamedadel7744-9853.vercel.app"
    website_platform_studio_url: str = "https://wp-studio-hamedadel7744-9853.vercel.app"
    website_platform_api_key: str = ""

    # §68: at-rest envelope encryption of Integration.credentials
    # (app.core.secrets.EnvelopeSecretStore). Base64-encoded; must decode to
    # at least 32 bytes. Empty is tolerated ONLY in local/test, where a
    # published dev-only key is used (loudly logged); secure environments
    # refuse to boot without it.
    secrets_master_key: str = ""
    # Comma-separated OLD master keys, kept for decryption only during a
    # rotation grace period (§69: existing rows must not break at switch-over).
    secrets_previous_master_keys: str = ""

    # ------------------------------------------------------------------
    # DELIMITED EDIT (Meta connect flow) — redirect URI derivation only.
    # META_OAUTH_REDIRECT_URI wins when set; otherwise the callback path is
    # derived from the canonical API public base URL (same value the
    # provider webhooks are registered under). No deploy needs a hardcoded
    # personal host, and an empty pair fails loudly in meta_oauth._meta_config.
    # ------------------------------------------------------------------
    @property
    def meta_oauth_redirect_uri_effective(self) -> str:
        explicit = self.meta_oauth_redirect_uri.strip()
        if explicit:
            return explicit
        base = self.api_public_base_url.strip().rstrip("/")
        if base:
            return f"{base}/api/v1/integrations/meta/oauth/callback"
        return ""

    # ------------------------------------------------------------------

    @property
    def is_secure_environment(self) -> bool:
        """True when this deployment must satisfy the production-grade checks.

        Several security behaviours key off `environment` — the OpenAPI schema
        is exposed when it is not "production" (main.py), HSTS is only sent for
        "production" (middleware.py), and the rate limiter is disabled for
        "test". So an unrecognised value must be treated as secure-required.
        """
        return self.environment not in _DEV_ENVIRONMENTS

    @property
    def auth_email_delivery_configured(self) -> bool:
        """Whether the durable auth-email worker is allowed to contact Resend."""
        return bool(
            self.email_delivery_enabled
            and self.resend_api_key.strip()
            and self.email_from.strip()
            and self.frontend_public_url.strip()
        )

    @property
    def object_storage_configured(self) -> bool:
        """Whether durable media storage has a complete S3-compatible setup."""
        return all(
            value.strip()
            for value in (
                self.s3_endpoint,
                self.s3_region,
                self.s3_bucket,
                self.s3_access_key_id,
                self.s3_secret_access_key,
            )
        )

    @property
    def supabase_storage_configured(self) -> bool:
        """Whether the server can use the Supabase Storage REST API."""
        return all(
            value.strip()
            for value in (
                self.supabase_url,
                self.supabase_service_role_key,
                self.s3_bucket,
            )
        )

    @property
    def durable_storage_configured(self) -> bool:
        """Whether either supported server-side Storage connection is ready."""
        return self.object_storage_configured or self.supabase_storage_configured

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
        # Both token sides are pinned to HS256 (see security.JWT_ALGORITHM);
        # a deploy that sets something else must not discover it as a
        # full-auth-outage at first request.
        if self.jwt_algorithm != "HS256":
            raise ValueError(f"JWT_ALGORITHM must be HS256 (pinned both sides) {where}")
        # Rotation is optional, but a HALF-configured rotation must not boot:
        # a weak or duplicated previous secret either weakens verification or
        # silently makes the rotation a no-op.
        if self.jwt_secret_previous:
            if len(self.jwt_secret_previous.encode()) < 32:
                raise ValueError(f"JWT_SECRET_PREVIOUS must be at least 32 bytes {where}")
            if self.jwt_secret_previous == self.jwt_secret:
                raise ValueError(f"JWT_SECRET_PREVIOUS must differ from JWT_SECRET {where}")
        if self.trusted_proxy_count < 0:
            raise ValueError(f"TRUSTED_PROXY_COUNT must not be negative {where}")
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
            raise ValueError(f"SECRETS_MASTER_KEY must decode to at least 32 bytes {where}")
        if self.cors_origins.strip() == "*":
            raise ValueError(f"CORS_ORIGINS must not be * {where}")

        s3_values = (
            self.s3_endpoint,
            self.s3_region,
            self.s3_access_key_id,
            self.s3_secret_access_key,
        )
        if any(value.strip() for value in s3_values) and not self.object_storage_configured:
            raise ValueError(
                "S3_ENDPOINT, S3_REGION, S3_BUCKET, S3_ACCESS_KEY_ID and "
                f"S3_SECRET_ACCESS_KEY must be configured together {where}"
            )
        supabase_storage_values = (self.supabase_url, self.supabase_service_role_key)
        if (
            any(value.strip() for value in supabase_storage_values)
            and not self.supabase_storage_configured
        ):
            raise ValueError(
                "SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY and S3_BUCKET must be "
                f"configured together for the Storage REST fallback {where}"
            )
        if self.is_secure_environment and not self.durable_storage_configured:
            raise ValueError(f"durable object storage must be configured {where}")
        if self.object_storage_configured:
            storage_endpoint = urlsplit(self.s3_endpoint)
            if (
                storage_endpoint.scheme not in {"https", "http"}
                or not storage_endpoint.netloc
                or storage_endpoint.username is not None
                or storage_endpoint.password is not None
                or storage_endpoint.query
                or storage_endpoint.fragment
                or (self.is_secure_environment and storage_endpoint.scheme != "https")
            ):
                raise ValueError(f"S3_ENDPOINT must be an HTTPS S3-compatible endpoint {where}")
        if self.supabase_storage_configured:
            storage_url = urlsplit(self.supabase_url)
            if (
                storage_url.scheme not in {"https", "http"}
                or not storage_url.netloc
                or storage_url.username is not None
                or storage_url.password is not None
                or storage_url.path not in {"", "/"}
                or storage_url.query
                or storage_url.fragment
                or (self.is_secure_environment and storage_url.scheme != "https")
            ):
                raise ValueError(f"SUPABASE_URL must be a project HTTPS URL without a path {where}")
        if not 1 <= self.s3_signed_url_ttl_seconds <= 7 * 24 * 60 * 60:
            raise ValueError("S3_SIGNED_URL_TTL_SECONDS must be between 1 and 604800")

        cors_values = [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]
        if not cors_values or "*" in cors_values:
            raise ValueError(f"CORS_ORIGINS must list explicit origins {where}")
        for origin in cors_values:
            parsed_origin = urlsplit(origin)
            if (
                not parsed_origin.netloc
                or parsed_origin.username is not None
                or parsed_origin.password is not None
                or parsed_origin.path
                or parsed_origin.query
                or parsed_origin.fragment
                or parsed_origin.scheme not in {"http", "https"}
                or (self.is_secure_environment and parsed_origin.scheme != "https")
            ):
                raise ValueError(
                    f"CORS_ORIGINS entries must be HTTPS origins in secure environments {where}"
                )

        if self.is_secure_environment and not self.email_delivery_enabled:
            if self.email_delivery_strict:
                raise ValueError(
                    f"EMAIL_DELIVERY_ENABLED must be true in secure environments {where}"
                )
            # Explicit soft-launch opt-out (EMAIL_DELIVERY_STRICT=false): boot
            # without email, LOUDLY — password-reset-by-email is unavailable
            # until the operator sets a Resend key and re-enables it.
            logger.warning(
                "EMAIL_DELIVERY_ENABLED=false in %s — password-reset-by-email "
                "is unavailable (email_delivery_strict=false soft-launch opt-out)",
                self.environment,
            )

        if self.email_delivery_enabled:
            if not self.resend_api_key.strip():
                raise ValueError(
                    f"RESEND_API_KEY is required when email delivery is enabled {where}"
                )
            if not self.email_from.strip() or "@" not in self.email_from:
                raise ValueError(f"EMAIL_FROM must be a verified sender address {where}")
            if any(char in self.email_from for char in "\r\n"):
                raise ValueError(f"EMAIL_FROM must be a single address {where}")
            parsed_frontend_url = urlsplit(self.frontend_public_url)
            if (
                not parsed_frontend_url.netloc
                or parsed_frontend_url.username is not None
                or parsed_frontend_url.password is not None
                or parsed_frontend_url.path not in {"", "/"}
                or parsed_frontend_url.query
                or parsed_frontend_url.fragment
            ):
                raise ValueError(f"FRONTEND_PUBLIC_URL must be an absolute public URL {where}")
            if self.is_secure_environment and parsed_frontend_url.scheme != "https":
                raise ValueError(f"FRONTEND_PUBLIC_URL must use HTTPS {where}")
            if parsed_frontend_url.scheme not in {"http", "https"}:
                raise ValueError(f"FRONTEND_PUBLIC_URL must use HTTP or HTTPS {where}")

        # DEBUG is NOT a hard failure: it only controls the log level, and
        # refusing to boot over log verbosity would take a running deployment
        # down for a cosmetic problem. It is logged loudly instead.
        if self.debug:
            logger.warning(
                "config.debug_enabled_in_secure_environment environment=%s — set DEBUG=false",
                self.environment,
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
