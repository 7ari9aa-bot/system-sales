"""Local Development Database Setup Helper (R-D7).

Usage:
    cd backend
    .venv/Scripts/python scripts/dev_db.py                 # up + migrate + provision + smoke
    .venv/Scripts/python scripts/dev_db.py --no-smoke      # skip a step
    .venv/Scripts/python scripts/dev_db.py --no-up         # use a database already running

Automates a local Postgres + Redis environment from infra/docker-compose.yml so
DB-backed tests can run locally instead of skipping.

Every child process runs with an EXPLICIT local environment (see _local_env).
That is not decoration: `scripts/provision.py` rewrites backend/.env, and an
inherited DATABASE_URL* from a developer's .env would otherwise let a "local
setup" helper migrate or provision a database it was never pointed at.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_ROOT.parent
COMPOSE_FILE = REPO_ROOT / "infra" / "docker-compose.yml"

# Must match infra/docker-compose.yml's postgres service.
LOCAL_DB_HOST_PORT = "localhost:5432"
LOCAL_DB_NAME = "sales"
LOCAL_APP_PASSWORD = "local-app-password"


def _local_env() -> dict[str, str]:
    """The explicit local environment every child process inherits."""
    admin = f"postgresql+asyncpg://postgres:postgres@{LOCAL_DB_HOST_PORT}/{LOCAL_DB_NAME}"
    app = (
        f"postgresql+asyncpg://sales_app:{LOCAL_APP_PASSWORD}"
        f"@{LOCAL_DB_HOST_PORT}/{LOCAL_DB_NAME}"
    )
    return {
        **os.environ,
        "ENVIRONMENT": "local",
        "DATABASE_URL": app,
        "DATABASE_URL_ADMIN": admin,
        "DATABASE_URL_APP": app,
        "DATABASE_URL_APP_ADMIN": app,
        "SALES_APP_DB_PASSWORD": LOCAL_APP_PASSWORD,
        "REDIS_URL": "redis://localhost:6379/0",
    }


def run_cmd(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    print(f">> {' '.join(cmd)}")
    completed = subprocess.run(
        cmd, cwd=str(BACKEND_ROOT), capture_output=True, text=True, env=_local_env()
    )
    if completed.stdout:
        print(completed.stdout.strip())
    if completed.returncode != 0:
        print(f"!! exited {completed.returncode}", file=sys.stderr)
        if completed.stderr:
            print(completed.stderr.strip(), file=sys.stderr)
        if check:
            sys.exit(completed.returncode)
    return completed


def wait_for_postgres(timeout: int = 45) -> bool:
    print(">> waiting for PostgreSQL...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        probe = subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                str(COMPOSE_FILE),
                "exec",
                "-T",
                "postgres",
                "pg_isready",
                "-U",
                "postgres",
            ],
            capture_output=True,
            text=True,
        )
        if probe.returncode == 0:
            print(">> PostgreSQL is ready")
            return True
        time.sleep(1.5)
    print("!! timed out waiting for PostgreSQL", file=sys.stderr)
    return False


def build_parser() -> argparse.ArgumentParser:
    """The CLI surface, exposed so a test can prove every step is optional."""
    parser = argparse.ArgumentParser(description="Local dev database helper")
    parser.add_argument(
        "--up",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="start the postgres and redis containers (--no-up to skip)",
    )
    parser.add_argument(
        "--migrate",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="run alembic upgrade head (--no-migrate to skip)",
    )
    parser.add_argument(
        "--provision",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="run scripts/provision.py (--no-provision to skip)",
    )
    parser.add_argument(
        "--smoke",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="run scripts/rls_smoke_test.py (--no-smoke to skip)",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()

    if not COMPOSE_FILE.exists():
        sys.exit(f"Error: {COMPOSE_FILE} not found")

    if args.up:
        print(">> starting postgres & redis via docker compose...")
        started = subprocess.run(
            ["docker", "compose", "-f", str(COMPOSE_FILE), "up", "-d", "postgres", "redis"],
            capture_output=True,
            text=True,
        )
        if started.returncode != 0:
            print("Docker compose failed — is Docker Desktop running?", file=sys.stderr)
            print(started.stderr, file=sys.stderr)
            sys.exit(1)
        if not wait_for_postgres():
            sys.exit(1)

    if args.migrate:
        print(">> migrations (alembic upgrade head)")
        run_cmd([sys.executable, "-m", "alembic", "upgrade", "head"])

    if args.provision:
        print(">> provisioning roles and RLS policies")
        run_cmd([sys.executable, str(BACKEND_ROOT / "scripts" / "provision.py")])

    if args.smoke:
        print(">> RLS isolation smoke test")
        run_cmd([sys.executable, str(BACKEND_ROOT / "scripts" / "rls_smoke_test.py")])

    print("\nLocal database environment is ready and verified.")
    print("DB-backed tests now run instead of skipping:")
    print("    .venv/Scripts/python -m pytest tests/ -q")


if __name__ == "__main__":
    main()
