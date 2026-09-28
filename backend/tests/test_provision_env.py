"""provision._write_app_password — the written DSNs derive from the provisioned DB.

Regression guard: the writer used to hardcode the production Supabase pooler
host, so `provision.py` run against a LOCAL database still repointed that
machine's .env at production — the live hazard the DATABASE_URL override in
ci.yml works around. The derivation itself is now pinned here: pooler URLs get
the <role>.<ref> login and the :6543/:5432 port split, everything else keeps
its own host, port and path.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

provision = importlib.import_module("provision")


def _write(tmp_path: Path, admin_url: str) -> dict[str, str]:
    env = tmp_path / ".env"
    provision._write_app_password("pw-123", admin_url, env_path=env)
    return {
        line.split("=", 1)[0]: line.split("=", 1)[1]
        for line in env.read_text().splitlines()
        if "=" in line
    }


def test_supabase_pooler_admin_url_yields_transaction_pooler_for_app(tmp_path):
    lines = _write(
        tmp_path,
        "postgresql+asyncpg://postgres.iixxqitfopsgvaheedlg:secret"
        "@aws-1-eu-west-1.pooler.supabase.com:5432/postgres",
    )
    assert lines["DATABASE_URL_APP"] == (
        "postgresql+asyncpg://sales_app.iixxqitfopsgvaheedlg:pw-123"
        "@aws-1-eu-west-1.pooler.supabase.com:6543/postgres"
    )
    assert lines["DATABASE_URL_APP_ADMIN"] == (
        "postgresql+asyncpg://sales_app.iixxqitfopsgvaheedlg:pw-123"
        "@aws-1-eu-west-1.pooler.supabase.com:5432/postgres"
    )
    # DATABASE_URL stays the app DSN — same transaction pooler the API uses.
    assert lines["DATABASE_URL"] == lines["DATABASE_URL_APP"]


def test_local_admin_url_stays_local_and_keeps_port_and_path(tmp_path):
    lines = _write(tmp_path, "postgresql+asyncpg://postgres:postgres@localhost:5432/sales")
    assert lines["DATABASE_URL_APP"] == "postgresql+asyncpg://sales_app:pw-123@localhost:5432/sales"
    assert (
        lines["DATABASE_URL_APP_ADMIN"]
        == "postgresql+asyncpg://sales_app:pw-123@localhost:5432/sales"
    )


def test_existing_database_url_lines_are_replaced_and_others_kept(tmp_path):
    env = tmp_path / ".env"
    env.write_text("DATABASE_URL=postgresql+asyncpg://stale@old-host:5432/db\nOTHER_KEY=keep\n")
    lines = _write(tmp_path, "postgresql+asyncpg://postgres:postgres@localhost:5432/sales")
    assert lines["DATABASE_URL"].startswith("postgresql+asyncpg://sales_app:")
    assert lines["OTHER_KEY"] == "keep"
    assert "old-host" not in env.read_text()
