"""§57 — retention is a CHOSEN policy, so the purge is a decision, not a drift.

`docs/GAP_REGISTER.md` removed `archive_old_rows` with the words "wiring
retention needs a partition DDL that does not exist, so a partial wire would
delete rows on a schedule nobody chose." The schedule now exists
(`partition.ensure_months` / `retention.purge_partitions`) and the DDL exists
(`f7a2c9d4e8b1`), which means the only thing standing between this commit and
the failure mode that comment describes is the plan function under test here.
So these cases are pure and run without a database: no rows, no session, no
mocked privileges — just the decision, which is the part that must be right.

The rule encoded below, in order:

1. Nothing drops unless EVERY active tenant has chosen a policy for the store.
   A tenant that never chose, or chose `paused`, PINS the whole shared month —
   because §56 partitions by time, not by tenant, so one month is everyone's
   month. Per-tenant shorter horizons stay with the existing row-level
   `retention.run` worker; only the longest one can be honoured by a DROP.
2. The longest chosen horizon is the binding one.
3. Below both, the database's own 13-month floor still refuses, so a policy
   that someone typed too aggressively cannot reach data the PII map protects.
"""

from __future__ import annotations

import inspect
import pathlib
from datetime import date

import pytest

from app.core import partitioning
from app.modules.analytics import retention

NOW = date(2026, 9, 15)  # a fixed "today" — a plan must never read the clock twice


def _months_back(count: int) -> list[date]:
    """First-of-month starts, oldest first, going back `count` months from NOW."""
    out: list[date] = []
    year, month = NOW.year, NOW.month
    for _ in range(count):
        month -= 1
        if month == 0:
            month, year = 12, year - 1
        out.append(date(year, month, 1))
    out.reverse()
    return out


def _gate(**kw):
    base = {"tenant_count": 1, "missing_policies": 0, "max_days": 500}
    base.update(kw)
    return retention.evaluate_gate(**base)


# ------------------------------------------------------- the named default --


def test_the_default_is_named_and_traces_to_the_spec_row_that_implies_it() -> None:
    """§57 says hot -> archive -> delete but never gives a number; §52 says the
    policy is per data class and executed by workers. The number comes from the
    store's own row in docs/PII_DATA_MAP.md, which is the only place in this
    repo that states a duration for `ai_usage`.
    """
    assert retention.DEFAULT_RETENTION_DAYS[retention.AI_USAGE_DATA_CLASS] == 390
    assert partitioning.PARTITION_DROP_FLOOR_MONTHS == 13
    source = retention.DEFAULT_RETENTION_SOURCE
    assert "PII_DATA_MAP" in source and "13 months" in source
    assert "§52" in inspect.getsource(retention)
    assert "§57" in inspect.getsource(retention)


def test_the_default_is_offered_never_written() -> None:
    """A default that is silently materialised as an `active` policy row IS the
    silent DELETE this task exists to avoid. The default may only be the value
    an opt-in surface pre-fills, and the database default for a new policy row
    is `paused` (see the migration), so nothing enforces anything until a
    tenant chooses it.
    """
    assert "active" not in retention.DEFAULT_OFFER_STATUS
    assert retention.DEFAULT_OFFER_STATUS == "paused"
    assert "ONLY WRITER" in inspect.getsource(retention.choose_policy)
    # The gate reads only the aggregate the database computes, never a tenant's
    # own policy rows, so no path here can enumerate another tenant's choices.
    assert "retention_policies" not in retention.DROP_GATE_SQL


def test_the_opt_in_surface_is_the_only_writer_and_states_its_two_values() -> None:
    choose = retention.choose_policy
    params = inspect.signature(choose).parameters
    assert {"session", "tenant_id", "data_class", "retention_days", "enabled"} <= set(params)
    assert params["enabled"].default is True
    doc = inspect.getdoc(choose) or ""
    assert "opt-in" in doc and "opt-out" in doc


# --------------------------------------------------- gate: nothing chosen ---


def test_a_tenant_that_chose_nothing_purges_nothing() -> None:
    gate = _gate(tenant_count=3, missing_policies=3, max_days=None)
    assert gate.may_drop is False
    plan = retention.build_purge_plan(months=_months_back(24), gate=gate, now=NOW)
    assert plan.droppable == ()
    assert plan.blocked_reason == retention.BLOCKED_NO_CHOSEN_POLICY


def test_one_silent_tenant_pins_the_shared_month_for_everyone() -> None:
    """2 of 3 tenants chose 500 days; the third never answered. The month is
    shared, so it cannot be dropped for the two and kept for the one — the
    conservative answer is to drop nothing and say why.
    """
    gate = _gate(tenant_count=3, missing_policies=1, max_days=500)
    plan = retention.build_purge_plan(months=_months_back(24), gate=gate, now=NOW)
    assert plan.droppable == ()
    assert plan.blocked_reason == retention.BLOCKED_NO_CHOSEN_POLICY
    assert plan.pinned_by_days is None


def test_no_active_tenants_is_not_permission_to_purge() -> None:
    plan = retention.build_purge_plan(
        months=_months_back(24),
        gate=_gate(tenant_count=0, missing_policies=0, max_days=500),
        now=NOW,
    )
    assert plan.droppable == ()
    assert plan.blocked_reason == retention.BLOCKED_NO_ACTIVE_TENANTS


# ------------------------------------------------ gate: something chosen ---


def test_an_opted_in_tenant_loses_exactly_the_months_it_should() -> None:
    gate = _gate(tenant_count=1, missing_policies=0, max_days=500)
    months = _months_back(24)  # 2024-10 .. 2026-08
    plan = retention.build_purge_plan(months=months, gate=gate, now=NOW)

    # 500 days before 2026-09-15 is 2025-05-03, so a month leaves only once it
    # is entirely before that AND entirely before 2025-08-01 (the 13-month
    # floor measured from the start of this month). The floor is the looser of
    # the two here, so the horizon is what binds.
    assert plan.droppable == tuple(m for m in months if m <= date(2025, 4, 1))
    assert plan.blocked_reason is None
    assert plan.pinned_by_days == 500
    # The most recent 14 months, and every month inside the floor, survive.
    assert date(2026, 8, 1) not in plan.droppable
    assert date(2025, 9, 1) not in plan.droppable
    assert date(2025, 5, 1) not in plan.droppable  # upper 2025-06-01 > cutoff
    assert date(2025, 4, 1) in plan.droppable  # upper 2025-05-01 <= cutoff


def test_the_longest_chosen_horizon_pins_the_others() -> None:
    """Two tenants: 500 and 900 days. `max_days` is therefore 900 and the
    500-day tenant's wish to drop more is NOT granted by the partition path —
    it is granted per-tenant by the row-level worker instead, which can.
    """
    months = _months_back(30)
    loose = retention.build_purge_plan(
        months=months, gate=_gate(tenant_count=2, max_days=500), now=NOW
    )
    strict = retention.build_purge_plan(
        months=months, gate=_gate(tenant_count=2, max_days=900), now=NOW
    )
    assert set(strict.droppable) < set(loose.droppable), (
        "the 900-day tenant's data was scheduled for deletion by the 500-day one"
    )
    assert strict.droppable == (), "900 days has not elapsed for any month present"
    assert strict.pinned_by_days == 900


def test_an_aggressive_policy_cannot_outrun_the_legal_floor() -> None:
    """A tenant (or a bug) choosing 30 days must still not reach a month that is
    12 months old: the PII map's 13 months for this store is enforced twice —
    here and, independently, inside the purge function in the database.
    """
    months = _months_back(24)
    plan = retention.build_purge_plan(
        months=months, gate=_gate(tenant_count=1, max_days=30), now=NOW
    )
    assert all(m <= date(2025, 7, 1) for m in plan.droppable), plan.droppable
    assert date(2025, 8, 1) not in plan.droppable  # 13 months is not over yet
    assert date(2026, 8, 1) not in plan.droppable


def test_a_non_positive_horizon_blocks_instead_of_deleting_everything() -> None:
    for days in (0, -5):
        gate = _gate(tenant_count=1, max_days=days)
        assert gate.may_drop is False
        assert gate.reason == retention.BLOCKED_NO_POSITIVE_HORIZON


def test_the_default_partition_is_never_a_purge_target() -> None:
    """Rows that had no month to land in live in `ai_usage_default`; detaching
    it would drop unroutable rows of every age at once, and it is not a month.
    """
    assert partitioning.is_default_partition("ai_usage_default") is True
    assert partitioning.is_default_partition("ai_usage_2025_01") is False


def test_month_bounds_are_utc_aware_and_half_open() -> None:
    assert partitioning.month_bounds(2026, 1) == (date(2026, 1, 1), date(2026, 2, 1))
    assert partitioning.month_bounds(2026, 12) == (date(2026, 12, 1), date(2027, 1, 1))
    with pytest.raises(ValueError):
        partitioning.month_bounds(2026, 13)


def test_plan_is_a_deterministic_pure_function_of_its_inputs() -> None:
    kwargs = {"months": _months_back(20), "gate": _gate(), "now": NOW}
    first = retention.build_purge_plan(**kwargs)
    second = retention.build_purge_plan(**kwargs)
    assert first == second
    assert isinstance(first.droppable, tuple)
    # purity: the function must not be able to touch a session at all
    assert "session" not in inspect.signature(retention.build_purge_plan).parameters


# --------------------------------------------------- module discipline --------


def test_retention_reads_policies_with_raw_sql_not_a_cross_module_import() -> None:
    """`retention_policies` belongs to `privacy`, and `tests/test_module_boundaries.py`
    ratchets cross-module imports at 94 — which must not rise. It also belongs to
    a FORCE-RLS table, so the cross-tenant tally cannot be done from Python at
    all: it runs as a SECURITY DEFINER aggregate in the database that returns
    only counts, never another tenant's rows.
    """
    src = pathlib.Path(retention.__file__).read_text(encoding="utf-8")
    assert "from app.modules" not in src, "a new cross-module import raises the boundary count"
    assert "import app.modules" not in src
    assert "retention_policies" in src, "the per-tenant surface must read the policy rows"
    gate_sql = retention.DROP_GATE_SQL
    assert "retention_drop_horizon" in gate_sql
    assert "status = 'active'" in retention.POLICY_READ_SQL
    assert "retention_days > 0" in retention.POLICY_READ_SQL


def test_retention_never_resolves_a_timezone_itself() -> None:
    """`analytics/timekit.py` is the only place a zone is resolved. Partition
    boundaries are UTC months by definition, so this module works in `date`
    values and must not reach for a zone, an offset, or the deployment default.
    """
    src = pathlib.Path(retention.__file__).read_text(encoding="utf-8")
    for forbidden in ("ZoneInfo", "astimezone", "ANALYTICS_TIMEZONE", "tz_convert"):
        assert forbidden not in src, f"{forbidden} belongs in timekit, not retention"
