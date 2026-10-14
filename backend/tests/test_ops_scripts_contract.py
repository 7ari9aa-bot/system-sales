"""Contract guards for the operational scripts in backend/scripts/.

These are DB-free and run everywhere (including a developer laptop with no
Postgres), which is the point: the defects they pin were all invisible until
someone ran the script against a real database — and two of them could never
have been caught by running the script at all, because the script reported
success while checking the wrong thing.

Each guard here failed on the previous version of its script.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = BACKEND_ROOT / "scripts"
REPO_ROOT = BACKEND_ROOT.parent


def _load_script(name: str):
    """Import a script by path (they are not a package and use `_bootstrap`)."""
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS_DIR / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------
# restore_drill.py (R-C8: it reported success while failing, and ran the RLS
# check against the ambient .env rather than the restore target)
# --------------------------------------------------------------------------


def test_restore_drill_parses_the_smoke_test_real_output() -> None:
    """The criterion must match what rls_smoke_test.py actually prints.

    The previous version searched stdout for the literal "7/7 PASS", which that
    script has never emitted (it prints one `[PASS] <name>` line per assertion),
    so the check reported PARTIAL forever and the drill still said it passed.
    """
    drill = _load_script("restore_drill")
    stdout = (
        "testing as: sales_app (bypassrls=false)\n\n"
        "RLS SMOKE TEST RESULTS\n  [PASS] a\n  [PASS] b\n  [FAIL] c\n"
    )
    passed, failed = drill.parse_smoke_stdout(stdout)
    assert (passed, failed) == (2, 1)
    assert drill.parse_smoke_stdout("no verdicts here") == (0, 0)


def test_restore_drill_fails_the_whole_drill_on_any_failed_check() -> None:
    """A failed check must reach the exit status (it did not before)."""
    drill = _load_script("restore_drill")
    assert drill.summarize({"a": {"status": "PASS"}}) == "PASS"
    assert drill.summarize({"a": {"status": "PASS"}, "b": {"status": "FAIL"}}) == "FAIL"


def test_restore_drill_skips_rls_instead_of_faking_it() -> None:
    """No app URL is a SKIPPED check with a reason, never PARTIAL and never PASS."""
    drill = _load_script("restore_drill")
    result = drill.run_rls_smoke(None)
    assert result["status"] == "SKIPPED"
    assert "app-url" in str(result["reason"])


def test_restore_drill_repoints_the_app_role_at_the_target_host() -> None:
    """The RLS check must run against the restored copy, not the ambient .env."""
    drill = _load_script("restore_drill")
    derived = drill.derive_app_url(
        "postgresql+asyncpg://postgres:postgres@restored.example:5432/sales",
        "postgresql+asyncpg://sales_app.secret@prod.example:5432/sales",
    )
    assert derived is not None
    assert "restored.example" in derived
    assert "sales_app" in derived
    assert "prod.example" not in derived


def test_restore_drill_counts_the_outbox_events_table() -> None:
    """`outbox` does not exist — the table is `outbox_events`."""
    drill = _load_script("restore_drill")
    assert "outbox_events" in drill._COUNTED_TABLES
    assert "outbox" not in drill._COUNTED_TABLES


def test_restore_drill_checks_the_real_invoice_guard_functions() -> None:
    """The guard names come from migrations e7a8b9c0d1e2 / a9b0c1d2e3f4."""
    drill = _load_script("restore_drill")
    assert drill._INVOICE_GUARD_FUNCTIONS == (
        "invoices_frozen_snapshot_guard",
        "invoices_truncate_guard",
    )


# --------------------------------------------------------------------------
# monitor_alerts.py (R-D9: the outbox alert was dead on a wrong table name,
# its failure was swallowed, and `pending` was used as if it were `lag`)
# --------------------------------------------------------------------------


def test_monitor_alerts_queries_the_real_outbox_table() -> None:
    import inspect

    monitor = _load_script("monitor_alerts")
    source = inspect.getsource(monitor.check_alerts)
    assert "FROM outbox_events" in source
    assert "FROM outbox " not in source


def test_monitor_alerts_treats_an_unreadable_outbox_as_an_alert() -> None:
    """Fail closed: an unknown relay state is not a healthy one."""
    import inspect

    monitor = _load_script("monitor_alerts")
    source = inspect.getsource(monitor.check_alerts)
    assert "outbox_check_failed" in source
    # The old version only recorded metrics["outbox_check_error"] and alerted nobody.


def test_monitor_alerts_does_not_mistake_pending_for_lag() -> None:
    """`pending` (delivered, unacked) is a different number from `lag`."""
    monitor = _load_script("monitor_alerts")
    assert monitor.resolve_lag({"lag": 5, "pending": 0}, None) == (5, "server_lag")
    # With a real measurement available, pending must NOT win.
    assert monitor.resolve_lag({"pending": 0}, 7) == (7, "last_delivered_id_range")
    # Only when nothing better exists is the proxy used, and it is labelled.
    assert monitor.resolve_lag({"pending": 3}, None) == (3, "pending_proxy")


def test_monitor_alerts_counts_every_documented_check() -> None:
    """The docstring's list and the RUNBOOK's list must not drift apart."""
    import inspect

    monitor = _load_script("monitor_alerts")
    source = inspect.getsource(monitor.check_alerts)
    for key in ("database", "outbox", "redis", "consumer_lag", "dlq", "api_readiness"):
        assert key in source, f"check {key!r} is documented but not implemented"
    # The 5xx-rate alert needs a metrics backend; the module must say so out loud
    # rather than print "All 5 ... healthy" while implementing four.
    assert "R-F2" in (monitor.__doc__ or "")


def test_monitor_alerts_reports_an_unreachable_database_instead_of_crashing() -> None:
    """An unreachable DB is the loudest 'not ready' — it must be an alert.

    The connect() call sits OUTSIDE the per-query try blocks, so without an
    explicit guard the script died with a traceback and reported nothing.
    """
    import inspect

    monitor = _load_script("monitor_alerts")
    source = inspect.getsource(monitor.check_alerts)
    assert "could not connect to the database" in source


def test_restore_drill_reports_an_unreachable_target_instead_of_crashing() -> None:
    import inspect

    drill = _load_script("restore_drill")
    source = inspect.getsource(drill.run_restore_drill)
    assert "database_connection" in source
    assert "except Exception" in source


def test_monitor_alerts_does_not_page_on_a_stream_that_does_not_exist_yet() -> None:
    """A missing stream is 'not applicable', not 'unknown'."""
    import inspect

    monitor = _load_script("monitor_alerts")
    source = inspect.getsource(monitor.check_alerts)
    assert "no such key" in source
    assert '"SKIPPED"' in source


# --------------------------------------------------------------------------
# dev_db.py (R-D9: all four flags were default=True + store_true, so no step
# could ever be turned off)
# --------------------------------------------------------------------------


@pytest.mark.parametrize("flag", ["up", "migrate", "provision", "smoke"])
def test_dev_db_steps_can_actually_be_disabled(flag: str) -> None:
    dev_db = _load_script("dev_db")
    parser = dev_db.build_parser()
    assert getattr(parser.parse_args([]), flag) is True
    assert getattr(parser.parse_args([f"--no-{flag}"]), flag) is False


def test_dev_db_pins_the_child_environment_to_local() -> None:
    """A 'local setup' helper must not inherit a production DATABASE_URL."""
    dev_db = _load_script("dev_db")
    env = dev_db._local_env()
    assert env["ENVIRONMENT"] == "local"
    for key in ("DATABASE_URL", "DATABASE_URL_ADMIN", "DATABASE_URL_APP"):
        assert "localhost" in env[key], f"{key} is not local"
        assert "supabase" not in env[key]


# --------------------------------------------------------------------------
# Wiring + docs (R-D9: "built, tested in isolation, called by nothing")
# --------------------------------------------------------------------------


def test_every_ops_script_is_reachable_from_the_runbook() -> None:
    runbook = (REPO_ROOT / "docs" / "RUNBOOK.md").read_text(encoding="utf-8")
    for script in (
        "dev_db.py",
        "restore_drill.py",
        "monitor_alerts.py",
        "sync_canonical_agent_prompts.py",
    ):
        assert script in runbook, f"{script} is not referenced by docs/RUNBOOK.md"


# --------------------------------------------------------------------------
# sync_canonical_agent_prompts.py — a prompt fix in a definition never reached
# the agent rows, because provisioning only re-syncs TOOLS on an existing agent
# and `publish` snapshots the ROW. Editing the file and publishing were both
# necessary and neither was sufficient.
# --------------------------------------------------------------------------


def test_prompt_digest_is_stable_and_short() -> None:
    script = _load_script("sync_canonical_agent_prompts")
    assert script.prompt_digest("abc") == script.prompt_digest("abc")
    assert script.prompt_digest("abc") != script.prompt_digest("abd")
    assert len(script.prompt_digest("abc")) == 12
    # A None prompt (a row that never had one) must not explode.
    assert len(script.prompt_digest(None)) == 12


def test_first_differing_line_points_at_the_change() -> None:
    script = _load_script("sync_canonical_agent_prompts")
    assert "line 2" in script.first_differing_line("a\nb\nc", "a\nX\nc")
    assert script.first_differing_line("a\nb", "a\nb") == "identical"
    # A shorter/longer prompt reports the first missing line, not an IndexError.
    assert "line 2" in script.first_differing_line("a", "a\nb")


def test_the_reconcile_targets_the_reply_only_customer_definition() -> None:
    """The script exists to push THIS text into the rows that still sell."""
    script = _load_script("sync_canonical_agent_prompts")
    definitions = script.canonical_definitions()
    assert "customer" in definitions
    prompt = definitions["customer"].system_prompt_template
    assert "ممنوع" in prompt
    assert "إتمام" not in prompt


def test_the_reconcile_refuses_a_remote_database_without_a_flag() -> None:
    script = _load_script("sync_canonical_agent_prompts")
    message = script._refuse_remote("db.example.supabase.co")
    assert "--allow-remote" in message
    assert "db.example.supabase.co" in message


def test_the_reconcile_defaults_to_a_dry_run() -> None:
    """Writing every tenant's prompt must be an explicit act, not the default."""
    script = _load_script("sync_canonical_agent_prompts")
    parser = script.build_parser()

    defaults = parser.parse_args([])
    assert defaults.apply is False, "the reconcile would write without being asked"
    assert defaults.publish is False
    assert defaults.allow_remote is False

    explicit = parser.parse_args(["--apply", "--publish", "--allow-remote"])
    assert explicit.apply is True
    assert explicit.publish is True
    assert explicit.allow_remote is True


def test_the_reconcile_never_publishes_a_row_it_did_not_update() -> None:
    """`--publish` alone would snapshot the OLD prompt into a new version."""
    import inspect

    script = _load_script("sync_canonical_agent_prompts")
    source = inspect.getsource(script.main)
    assert "publish and not args.apply" in source


def test_runbook_does_not_promise_the_smoke_test_prints_7_of_7() -> None:
    """rls_smoke_test.py prints per-assertion verdicts, not "7/7 PASS"."""
    runbook = (REPO_ROOT / "docs" / "RUNBOOK.md").read_text(encoding="utf-8")
    assert "7/7 PASS" not in runbook


# --------------------------------------------------------------------------
# reconcile_prod_agent_prompts.py — the management-token path to the same
# reconcile (the API never returns the database password, but it runs SQL).
# --------------------------------------------------------------------------


def test_the_api_reconcile_is_documented_in_the_runbook() -> None:
    runbook = (REPO_ROOT / "docs" / "RUNBOOK.md").read_text(encoding="utf-8")
    assert "reconcile_prod_agent_prompts.py" in runbook
    # The runbook must say WHY this path exists: the token cannot yield a DSN.
    assert "[YOUR-PASSWORD]" in runbook


def test_the_api_reconcile_defaults_to_a_dry_run() -> None:
    """Writing production must be an explicit act, not the default."""
    import inspect

    script = _load_script("reconcile_prod_agent_prompts")
    source = inspect.getsource(script.main)
    assert '"--apply", action="store_true"' in source
    assert "default=True" not in source, "a write path defaulted to on"


def test_the_api_reconcile_refuses_to_run_without_a_token(monkeypatch) -> None:
    import sys

    script = _load_script("reconcile_prod_agent_prompts")
    monkeypatch.delenv("SUPABASE_ACCESS_TOKEN", raising=False)
    monkeypatch.setattr(sys, "argv", ["reconcile_prod_agent_prompts.py", "--ref", "some-ref"])
    with pytest.raises(SystemExit, match="no Supabase access token"):
        script.main()


def test_the_api_reconcile_never_touches_a_customised_prompt_by_default() -> None:
    """Only a KNOWN stale canonical prompt is a copy; everything else is a decision."""
    script = _load_script("reconcile_prod_agent_prompts")
    import inspect

    source = inspect.getsource(script._build_sql)
    assert "--force" not in source  # the flag is consumed in main(), not in the SQL
    assert script.STALE_MARKER and "إتمام" in script.STALE_MARKER
