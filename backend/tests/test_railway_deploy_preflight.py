from __future__ import annotations

import pytest

from scripts.deploy_railway import _load_deployment_config


def _write_env(tmp_path, **overrides) -> str:
    values = {
        "DATABASE_URL": "postgresql+asyncpg://app:fake@db.example.test/sales",
        "DATABASE_URL_ADMIN": "postgresql+asyncpg://owner:fake@db.example.test/sales",
        "JWT_SECRET": "stable-test-signing-key-longer-than-32-bytes",
        "FRONTEND_PUBLIC_URL": "https://sales.example.test",
        "EMAIL_DELIVERY_ENABLED": "true",
        "RESEND_API_KEY": "re_test_key",
        "EMAIL_FROM": "Security <security@sales.example.test>",
        "S3_ENDPOINT": "https://project-ref.supabase.co/storage/v1/s3",
        "S3_REGION": "eu-west-1",
        "S3_BUCKET": "sales-media",
        "S3_ACCESS_KEY_ID": "test-access-key",
        "S3_SECRET_ACCESS_KEY": "test-secret-key",
    }
    values.update(overrides)
    path = tmp_path / ".env.production"
    path.write_text("\n".join(f"{key}={value}" for key, value in values.items()))
    return str(path)


def test_railway_preflight_requires_a_migration_owner_connection(tmp_path) -> None:
    env_file = _write_env(tmp_path, DATABASE_URL_ADMIN="")

    with pytest.raises(SystemExit, match="DATABASE_URL_ADMIN"):
        _load_deployment_config(env_file, None)


def test_railway_preflight_requires_password_reset_delivery_before_provisioning(
    tmp_path,
) -> None:
    env_file = _write_env(
        tmp_path,
        EMAIL_DELIVERY_ENABLED="false",
        RESEND_API_KEY="",
        EMAIL_FROM="",
    )

    with pytest.raises(SystemExit, match="EMAIL_DELIVERY_ENABLED"):
        _load_deployment_config(env_file, None)


def test_railway_preflight_requires_a_stable_strong_jwt_secret(tmp_path) -> None:
    env_file = _write_env(tmp_path, JWT_SECRET="short")

    with pytest.raises(SystemExit, match="stable JWT_SECRET"):
        _load_deployment_config(env_file, None)


def test_railway_preflight_accepts_explicit_https_origins(tmp_path) -> None:
    env_file = _write_env(
        tmp_path,
        CORS_ORIGINS="https://sales.example.test,https://admin.example.test",
    )

    env, frontend_url, cors_origins = _load_deployment_config(env_file, None)

    assert env["DATABASE_URL_ADMIN"].startswith("postgresql+asyncpg://owner:")
    assert frontend_url == "https://sales.example.test"
    assert cors_origins == "https://sales.example.test,https://admin.example.test"
    assert env["S3_ENDPOINT"] == "https://project-ref.supabase.co/storage/v1/s3"


def test_railway_preflight_requires_complete_supabase_storage_config(tmp_path) -> None:
    env_file = _write_env(tmp_path, S3_SECRET_ACCESS_KEY="")

    with pytest.raises(SystemExit, match="S3_SECRET_ACCESS_KEY"):
        _load_deployment_config(env_file, None)


def test_railway_preflight_rejects_insecure_storage_endpoint(tmp_path) -> None:
    env_file = _write_env(
        tmp_path,
        S3_ENDPOINT="http://project-ref.supabase.co/storage/v1/s3",
    )

    with pytest.raises(SystemExit, match="S3_ENDPOINT must be an HTTPS"):
        _load_deployment_config(env_file, None)
