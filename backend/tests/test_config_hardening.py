"""Configuration must fail CLOSED outside local/test (review G-05).

`_refuse_insecure_production` ran only when `environment == "production"`, but
`environment` DEFAULTS to "local" — so a deploy that forgot to set ENVIRONMENT,
or misspelled it "prod", validated nothing. That is not hypothetical harm:

* `main.py` exposes the OpenAPI schema whenever environment != "production".
* `middleware.py` only sends HSTS for "production".
* `middleware.py` disables the rate limiter for "test".

So an unrecognised value silently weakened several security behaviours at once,
while the app ran on the publicly-known default JWT secret.

These tests pin the inversion: everything that is not an explicitly recognised
development environment must satisfy the production-grade checks.
"""

from __future__ import annotations

import base64
import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings

SECURE = {
    "jwt_secret": "k" * 40,
    "service_token_internal": "internal-token-" + "v" * 24,
    "cors_origins": "https://app.example.com",
    "s3_endpoint": "https://project-ref.supabase.co/storage/v1/s3",
    "s3_region": "eu-west-1",
    "s3_bucket": "sales-media",
    "s3_access_key_id": "test-access-key",
    "s3_secret_access_key": "test-secret-key",
    # §68: secure environments also refuse to boot without a master key that
    # base64-decodes to >= 32 bytes.
    "secrets_master_key": base64.b64encode(b"m" * 32).decode(),
}
INSECURE = {
    "jwt_secret": "change-me",
    "service_token_internal": "change-me-too",
    "cors_origins": "*",
}


def _build(environment: str, **overrides) -> Settings:
    """Always pass the security fields explicitly so an ambient env var in the
    test process cannot make these assertions lie."""
    values = {**SECURE, **overrides}
    if environment.lower() not in {"local", "test"}:
        values.setdefault("email_delivery_enabled", True)
        values.setdefault("resend_api_key", "re_test_key")
        values.setdefault("email_from", "security@app.example.com")
        values.setdefault("frontend_public_url", "https://app.example.com")
    return Settings(environment=environment, **values)


# ------------------------------------------------- development is exempt --


@pytest.mark.parametrize("env", ["local", "test"])
def test_development_environments_accept_insecure_defaults(env: str) -> None:
    """A developer must be able to run the stack with no configuration."""
    settings = Settings(environment=env, **INSECURE)
    assert settings.is_secure_environment is False


@pytest.mark.parametrize("env", ["local", "test"])
def test_development_environments_do_not_require_a_long_jwt_secret(env: str) -> None:
    Settings(environment=env, **{**INSECURE, "jwt_secret": "short"})


# --------------------------------------- everything else fails closed ------


@pytest.mark.parametrize("env", ["production", "staging", "prod", "", "Production"])
def test_insecure_defaults_are_refused_outside_development(env: str) -> None:
    """`staging` and a misspelled `prod` are the point of this test."""
    with pytest.raises(ValidationError):
        Settings(environment=env, **INSECURE)


@pytest.mark.parametrize("env", ["production", "staging", "prod", ""])
def test_a_short_jwt_secret_is_refused_outside_development(env: str) -> None:
    with pytest.raises(ValidationError):
        _build(env, jwt_secret="short")


@pytest.mark.parametrize("env", ["production", "staging", "prod", ""])
def test_a_wildcard_cors_origin_is_refused_outside_development(env: str) -> None:
    with pytest.raises(ValidationError):
        _build(env, cors_origins="*")


@pytest.mark.parametrize("env", ["production", "staging", "prod", ""])
def test_an_unset_service_token_is_refused_outside_development(env: str) -> None:
    with pytest.raises(ValidationError):
        _build(env, service_token_internal="change-me-too")


@pytest.mark.parametrize("env", ["production", "staging", "prod", ""])
def test_secure_values_are_accepted_outside_development(env: str) -> None:
    settings = _build(env)
    assert settings.is_secure_environment is True


def test_whitespace_padded_wildcard_is_still_a_wildcard() -> None:
    with pytest.raises(ValidationError):
        _build("staging", cors_origins=" * ")


def test_an_explicit_origin_list_is_accepted() -> None:
    settings = _build(
        "staging", cors_origins="https://a.example.com,https://b.example.com"
    )
    assert settings.is_secure_environment is True


def test_secure_environment_requires_configured_password_reset_delivery() -> None:
    with pytest.raises(ValidationError, match="EMAIL_DELIVERY_ENABLED"):
        _build("production", email_delivery_enabled=False)
    # The soft-launch opt-out: an EXPLICIT email_delivery_strict=false boots
    # production without email (degraded on purpose), while the default
    # strict=True keeps the hard requirement for everyone else.
    _build("production", email_delivery_enabled=False, email_delivery_strict=False)
    with pytest.raises(ValidationError, match="EMAIL_DELIVERY_ENABLED"):
        _build("production", email_delivery_enabled=False, email_delivery_strict=True)


def test_secure_environment_requires_durable_media_storage() -> None:
    with pytest.raises(ValidationError, match="durable S3-compatible media storage"):
        _build(
            "production",
            s3_endpoint="",
            s3_region="",
            s3_bucket="",
            s3_access_key_id="",
            s3_secret_access_key="",
        )


def test_secure_environment_refuses_http_object_storage() -> None:
    with pytest.raises(ValidationError, match="S3_ENDPOINT"):
        _build("staging", s3_endpoint="http://project-ref.supabase.co/storage/v1/s3")


def test_secure_environment_refuses_partial_object_storage_configuration() -> None:
    with pytest.raises(ValidationError, match="must be configured together"):
        _build("production", s3_secret_access_key="")


def test_password_reset_frontend_url_cannot_contain_credentials_or_fragments() -> None:
    with pytest.raises(ValidationError, match="FRONTEND_PUBLIC_URL"):
        _build("staging", frontend_public_url="https://user:pass@app.example.com/#token")


def test_secure_cors_origins_must_be_https_origins_without_paths() -> None:
    with pytest.raises(ValidationError, match="CORS_ORIGINS"):
        _build("production", cors_origins="https://app.example.com/dashboard")


# ------------------------------------------------ is_secure_environment ----


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ("local", False),
        ("test", False),
        ("staging", True),
        ("production", True),
        ("prod", True),  # a typo must not buy an exemption
        ("", True),
    ],
)
def test_is_secure_environment(env: str, expected: bool) -> None:
    assert _build(env).is_secure_environment is expected


# ------------------------------------------------------------- DEBUG -------


def test_debug_defaults_to_false(monkeypatch) -> None:
    """The SECURE direction: an unset DEBUG must not turn verbose logging on
    in production (it used to default True — a deploy that never set it ran
    loud). Local development sets DEBUG=true explicitly."""
    monkeypatch.delenv("DEBUG", raising=False)
    settings = Settings(_env_file=None, environment="local", jwt_secret="change-me")
    assert settings.debug is False


def test_debug_outside_development_warns_but_does_not_block_startup(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Refusing to boot over log verbosity would take a deployment down for a
    cosmetic problem; it is logged loudly instead."""
    with caplog.at_level(logging.WARNING, logger="app.core.config"):
        settings = _build("staging", debug=True)

    assert settings.debug is True
    assert any(
        "debug_enabled_in_secure_environment" in record.message
        for record in caplog.records
    ), "debug outside development must be reported"


def test_debug_off_outside_development_is_silent(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="app.core.config"):
        _build("staging", debug=False)

    assert not [
        r for r in caplog.records if "debug_enabled_in_secure_environment" in r.message
    ]


# ------------------------- JWT pinning, rotation secret, proxy hop count ----


@pytest.mark.parametrize("env", ["production", "staging", "prod", ""])
def test_a_non_hs256_algorithm_is_refused_outside_development(env: str) -> None:
    """Encode and decode are pinned to the same algorithm in security.py; a
    deploy that sets something else must fail at boot, not at first login."""
    with pytest.raises(ValidationError, match="JWT_ALGORITHM"):
        _build(env, jwt_algorithm="HS512")


def test_development_may_not_set_a_foreign_algorithm_without_consequence() -> None:
    """Local/test keeps the permissive branch (the value is ignored by the
    pinned encoder/decoder), so this only pins that it does NOT raise."""
    Settings(environment="local", **{**INSECURE, "jwt_algorithm": "HS512"})


@pytest.mark.parametrize("env", ["production", "staging", "prod", ""])
def test_a_short_previous_secret_is_refused(env: str) -> None:
    with pytest.raises(ValidationError, match="JWT_SECRET_PREVIOUS"):
        _build(env, jwt_secret_previous="short")


@pytest.mark.parametrize("env", ["production", "staging", "prod", ""])
def test_a_previous_secret_equal_to_current_is_refused(env: str) -> None:
    with pytest.raises(ValidationError, match="JWT_SECRET_PREVIOUS"):
        _build(env, jwt_secret_previous=SECURE["jwt_secret"])


def test_a_well_formed_previous_secret_is_accepted() -> None:
    settings = _build("production", jwt_secret_previous="p" * 40)
    assert settings.jwt_secret_previous == "p" * 40


@pytest.mark.parametrize("env", ["production", "staging", "prod", ""])
def test_a_half_configured_rotation_is_refused(env: str) -> None:
    """JWT_SECRET_PREVIOUS set while the CURRENT secret is still the public
    default must not boot: a rotation pair of (public, private) is no rotation
    at all — the half-configured state fails at boot, never mid-flight."""
    with pytest.raises(ValidationError):
        _build(env, jwt_secret="change-me", jwt_secret_previous="p" * 40)


@pytest.mark.parametrize("env", ["production", "staging", "prod", ""])
def test_a_negative_trusted_proxy_count_is_refused(env: str) -> None:
    with pytest.raises(ValidationError, match="TRUSTED_PROXY_COUNT"):
        _build(env, trusted_proxy_count=-1)


# ------------------------------------------- an UNSET variable must fail ----
#
# The tests above pass `environment=` as a CONSTRUCTOR ARGUMENT. That is not the
# same thing as the variable being unset: an unset variable yields the field
# DEFAULT, and the default used to be "local" — which is in the dev set, so a
# deploy that forgot ENVIRONMENT skipped every check while these tests passed.
# Review G-05 flagged exactly that gap. These two close it.


def test_an_unset_environment_defaults_to_production(monkeypatch) -> None:
    monkeypatch.delenv("ENVIRONMENT", raising=False)

    settings = Settings(
        _env_file=None,
        **SECURE,
        email_delivery_enabled=True,
        resend_api_key="re_test_key",
        email_from="security@app.example.com",
        frontend_public_url="https://app.example.com",
    )

    assert settings.environment == "production", (
        "an unset ENVIRONMENT must default to the SECURE environment, not a dev one"
    )
    assert settings.is_secure_environment is True


def test_an_unset_environment_with_insecure_defaults_refuses_to_start(
    monkeypatch,
) -> None:
    """The whole point: forgetting the variable must fail closed, not run open."""
    monkeypatch.delenv("ENVIRONMENT", raising=False)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


# --------------------------- importing a module must not need secrets ------
#
# `app/core/db.py` built its engine at MODULE SCOPE (`engine = _create_engine()`),
# so merely importing it required a fully valid production configuration.
# `from app.core.db import bind_tenant` therefore raised "JWT_SECRET must be set
# in environment 'production'" inside ops scripts that never touch a JWT — which
# is how four scripts under `scripts/` became un-runnable outside CI. These tests
# pin the boundary: importing the module is free, USING a session still fails
# closed.
#
# They run in a SUBPROCESS because `app.core.db` is already imported in this
# process, so an in-process assertion could not observe import-time behaviour.

BACKEND_ROOT = Path(__file__).resolve().parent.parent


def _run(
    args: list[str], *, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Run in a fresh interpreter with ENVIRONMENT and JWT_SECRET removed.

    Removed rather than set: the behaviour under test is what happens when an
    operator has NOT stated the environment.
    """
    child = {
        k: v for k, v in os.environ.items() if k not in {"ENVIRONMENT", "JWT_SECRET"}
    }
    child["PYTHONPATH"] = str(BACKEND_ROOT)
    if env:
        child.update(env)
    return subprocess.run(
        [sys.executable, *args],
        capture_output=True,
        text=True,
        env=child,
        cwd=BACKEND_ROOT,
        timeout=180,
    )


def test_importing_the_database_module_does_not_require_production_secrets() -> None:
    """An ops script must be able to import the db helpers it actually uses."""
    result = _run(
        [
            "-c",
            "import app.core.db; from app.core.db import bind_tenant, get_sessionmaker; "
            "print('imported')",
        ]
    )

    assert result.returncode == 0, result.stderr
    assert "imported" in result.stdout


def test_using_the_engine_without_secrets_still_fails_closed() -> None:
    """Laziness must not become "no validation at all".

    The engine is built on first use, so the checks that used to run at import
    now run at first database access — they must still run.
    """
    result = _run(
        ["-c", "import app.core.db; app.core.db.get_engine()"],
        env={"ENVIRONMENT": "production", "JWT_SECRET": "change-me"},
    )

    assert result.returncode != 0, "a misconfigured deploy must not build an engine"
    assert "JWT_SECRET" in result.stderr


def test_an_ops_script_without_an_environment_says_what_to_set() -> None:
    """The failure an operator actually sees must be actionable.

    It used to be a bare pydantic traceback about a JWT secret, which reads like
    a bug in the script rather than a missing variable.
    """
    result = _run(["scripts/backfill_tenant_defaults.py"])

    assert result.returncode == 2, result.stdout + result.stderr
    assert "cannot load application settings" in result.stdout
    assert "ENVIRONMENT=production" in result.stdout, (
        "the message must say which variable to set"
    )
    assert "Traceback (most recent call last)" not in result.stdout + result.stderr, (
        "an operator must get instructions, not a stack trace"
    )

