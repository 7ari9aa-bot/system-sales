"""G-04 (the internal half): every worker shipped here is started by exactly
one deployment artifact, and no worker can be added without being declared.

The defect class this guards
----------------------------
``docs/ROADMAP_TO_90.md`` tracks G-04 as "worker deployment proof", and the
part of it that is external — running a worker in a real production container —
cannot be proven from this repo. What CAN be proven, and was not, is the
predicate that makes the external half meaningful: that for each worker there
exists a committed artifact whose start command boots it, exactly once, and that
a worker merged tomorrow cannot slip in undeclared.

That failure already bit this project twice (``0730cfa`` wired or retired four
orphan modules; ``test_contract_reachability.py`` documents an envelope that was
"unit-tested IN ISOLATION" while the production path skipped it). A worker no
artifact starts is the same bug one level up: complete, unit-tested, never
running. And a worker started TWICE is not better — the stream pools lean on
``FOR UPDATE SKIP LOCKED`` plus a per-row lock as their lease, which survives
replicas, but the scheduler-dispatched sweeps and the pollers claim work that a
second copy in the same process can grab concurrently through a different door.

The technique
-------------
Nothing here hardcodes a list of workers — a list the next author must remember
to edit is the same bug in a different file. Instead:

1. **Discovery is structural.** ``pkgutil`` walks ``app/workers/`` and imports
   every module; every concrete ``StreamWorker`` subclass *defined* there is a
   worker this codebase ships. An abstract base (one another discovered class
   inherits from) is not.
2. **A start path is also structural.** A worker is started either by a
   ``run.py`` POOLS entry (a stream pool / poller process) or by a handler the
   scheduler dispatches by ``job_type`` (``scheduler_worker._HANDLERS``, read
   out of the handler's own bytecode constants — the registration is the
   declaration). Both at once is a double-start.
3. **The artifacts are the real files**, parsed as text: ``railway.json``,
   ``infra/Dockerfile.backend``, ``infra/docker-compose.yml``,
   ``.github/workflows/*.yml``, ``app/main.py``. A start command that names no
   pool means "all of them" (``run.py``'s argparse default).

Rule 3 is what this file was written because of: before it, the only thing in
the repo that ever ran ``python -m app.workers.run`` was
``backend/scripts/deploy_railway.py`` — a manual provisioning script that no CI
job executes and that ``railway.json`` does not reference. Every declarative
artifact started the API and nothing started a worker.

Intended vs declared
--------------------
A worker may deliberately not run in the current deployment. That is a decision
to record, not to hide, and there are two axes to record it on:
``UNDISPATCHED_WORKERS`` (a worker class with no start path) and
``TOPOLOGY_START_GAPS`` (a deployment topology that does not start the pools).
Each entry carries a reason, and a separate assertion requires the situation to
still be the one described — wiring the thing later turns the record red and
forces it to be deleted. ``UNDISPATCHED_WORKERS`` is only ever consulted for
classes that are NOT ``StreamWorker`` subclasses, so a new stream pool can never
be excused out of the guard.

What this file found the first time it ran
------------------------------------------
* ``RetentionWorker`` had TWO start paths: pool ``retention`` and the scheduler's
  ``retention.run`` sweep. The pool half could never fire — ``handle()`` only
  acts on a payload whose ``event_type`` is ``retention.run``, and a stream name
  comes from the aggregate type (``core/events/writer.py:105``), so no producer
  can route such an event to the ``platform.events`` stream it subscribes to.
  The dead pool is gone; the durable sweep is the single trigger.
* ``journey.resume`` was produced by ``marketing/journey.py:_handle_delay`` with
  NO handler registered, so every delayed journey step was claimed and written
  back ``failed / "no handler for journey.resume"``.
* ``OffboardingWorker.run_once`` is dispatched by a global, hourly sweep. It
  enumerates only matured offboarding tenants, binds each tenant, and commits
  each cascade independently; a lifecycle reactivation and the purge serialize
  on the tenant row lock.
* Nothing declarative started any pool. Every artifact started the API; the only
  worker start command in the repo sat inside a manual provisioning script.

DB-free and Redis-free: discovery imports the modules, it never connects. The
``app.core.db`` engine is created lazily per session, so this runs locally with
no ``DATABASE_URL_APP_ADMIN``.
"""

from __future__ import annotations

import ast
import importlib
import pathlib
import pkgutil
import re
from collections.abc import Iterator
from types import CodeType, ModuleType

import pytest

from app.workers import job_runner
from app.workers import run as worker_run
from app.workers import scheduler_worker as scheduler
from app.workers.base import StreamWorker

# ----------------------------------------------------------------- topology --

#: <repo>/backend/tests/test_worker_deployment_declaration.py
BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent

WORKER_PACKAGE = "app.workers"

#: Deployment artifacts a deploy actually reads, grouped by the RUNTIME
#: topology each one produces. Coverage of the pools is asserted against these:
#: a start command living only in a hand-run script is not a deployment, it is
#: an instruction to whoever remembers to run it.
#:
#: ``infra/Dockerfile.backend`` sits in the Railway topology because that is
#: what builds it and inherits its CMD as the container's default command; the
#: compose services set ``command`` explicitly, so the default is not theirs.
DECLARATIVE_TOPOLOGIES: dict[str, tuple[pathlib.Path, ...]] = {
    "railway": (
        REPO_ROOT / "railway.json",
        REPO_ROOT / "infra" / "Dockerfile.backend",
    ),
    "compose": (REPO_ROOT / "infra" / "docker-compose.yml",),
}

#: CI workflow files are declarative artifacts, but they deploy nothing at
#: runtime — they run the test suite. They are scanned for coverage and asserted
#: (separately) to start no pool at all.
CI_ARTIFACTS: tuple[pathlib.Path, ...] = tuple(
    sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml"))
    + sorted((REPO_ROOT / ".github" / "workflows").glob("*.yaml"))
)

DECLARATIVE_ARTIFACTS: tuple[pathlib.Path, ...] = (
    *(a for group in DECLARATIVE_TOPOLOGIES.values() for a in group),
    *CI_ARTIFACTS,
)

#: Artifacts that start something but are not declarative (manual scripts).
#: Scanned so the guard knows the pool IS runnable, never so it counts as
#: deployed.
OPERATIONAL_ARTIFACTS: tuple[pathlib.Path, ...] = (
    BACKEND_ROOT / "scripts" / "deploy_railway.py",
)

#: Artifacts whose start command boots the API tier. None of them may also boot
#: a pool — see ``test_the_api_process_starts_no_worker_and_no_relay``.
API_ARTIFACTS: tuple[pathlib.Path, ...] = (
    REPO_ROOT / "railway.json",
    REPO_ROOT / "infra" / "Dockerfile.backend",
    REPO_ROOT / "infra" / "docker-compose.yml",
    BACKEND_ROOT / "scripts" / "deploy_railway.py",
)

API_MODULE = BACKEND_ROOT / "app" / "main.py"
CI_DIR = REPO_ROOT / ".github" / "workflows"

#: The ASGI app every API start command names. Used to catch a start command
#: that runs the API and a worker pool as one shell line — see
#: ``test_no_api_start_command_hides_a_worker_pool``.
API_ENTRYPOINT = "app.main:app"

#: The worker-pool entrypoint, spelled as it appears in a start command.
WORKER_ENTRYPOINT = "app.workers.run"

# --------------------------------------------------------------- discovery --


def _worker_modules() -> Iterator[ModuleType]:
    """Every module under ``app/workers/``, imported fresh from the package."""
    package = importlib.import_module(WORKER_PACKAGE)
    for info in pkgutil.iter_modules([str(pathlib.Path(package.__file__).parent)]):
        yield importlib.import_module(f"{WORKER_PACKAGE}.{info.name}")


def _classes_defined_in_workers() -> dict[str, type]:
    """Every class DEFINED by a worker module (not merely imported by one)."""
    found: dict[str, type] = {}
    for module in _worker_modules():
        for name, obj in vars(module).items():
            if isinstance(obj, type) and obj.__module__ == module.__name__:
                found[name] = obj
    return found


def _stream_workers() -> set[type[StreamWorker]]:
    """Concrete ``StreamWorker`` subclasses shipped by this package.

    "Concrete" is derived, not declared: a class another discovered class
    inherits from is a base (``StreamWorker`` itself, or a future shared
    mid-layer) and is not something a deployment can start.
    """
    all_classes = {
        obj
        for obj in _classes_defined_in_workers().values()
        if issubclass(obj, StreamWorker)
    }
    return {
        cls
        for cls in all_classes
        if not any(other is not cls and issubclass(other, cls) for other in all_classes)
    }


def _handler_referred_classes(handler: object) -> set[str]:
    """Class names a job handler mentions, read from its own bytecode.

    Handlers import lazily inside the function body
    (``from app.workers.retention_worker import RetentionWorker``), so the name
    lands in ``co_names`` of the function's code object. Recursing into nested
    code objects covers a handler that defines a closure. This is why the
    dispatch map needs no hand-maintained roster: the registration IS the
    declaration.
    """
    code = getattr(handler, "__code__", None)
    if not isinstance(code, CodeType):
        return set()
    names: set[str] = set(code.co_names)
    for const in code.co_consts:
        if isinstance(const, CodeType):
            names |= _handler_referred_classes(type("X", (), {"__code__": const}))
    return names


def _start_paths() -> dict[str, list[str]]:
    """worker class name -> every declared start path, pool or job type.

    A path is named so a failure can point at the offending line: ``pool:jobs``
    for a POOLS entry, ``job_type:retention.run`` for a scheduler dispatch.
    """
    paths: dict[str, list[str]] = {}
    for pool, cls in worker_run.POOLS.items():
        paths.setdefault(cls.__name__, []).append(f"pool:{pool}")
    for job_type, handler in scheduler._HANDLERS.items():  # noqa: SLF001 — the registry
        for name in _handler_referred_classes(handler):
            if name in _classes_defined_in_workers():
                paths.setdefault(name, []).append(f"job_type:{job_type}")
    for sweep_name, (_interval, handler) in scheduler.GLOBAL_SWEEPERS.items():
        for name in _handler_referred_classes(handler):
            if name in _classes_defined_in_workers():
                paths.setdefault(name, []).append(f"global_sweep:{sweep_name}")
    return {name: sorted(set(p)) for name, p in paths.items()}


# ------------------------------------------------------------- the record ---

#: Worker classes that deliberately have no start path today, and why. Wiring
#: one turns ``test_recorded_undispatched_workers_are_still_undispatched`` red,
#: which is the guard telling its author to delete the entry.
UNDISPATCHED_WORKERS: dict[str, str] = {
}

#: A topology whose declarative artifacts do not start every pool, and why that
#: is recorded here rather than fixed in this file. This is the intended-vs-
#: declared distinction made machine-checkable: the gap is REAL, stated, and
#: asserted to still be a gap — closing it in the artifact turns
#: ``test_each_topology_starts_every_pool_or_records_why_not`` red and forces
#: the excuse to be deleted. It is never a licence to leave a pool undeclared
#: everywhere: that is what the coverage test above fails on.
TOPOLOGY_START_GAPS: dict[str, str] = {
    # A Railway `railway.json` describes exactly ONE service, and the one this
    # repo carries is the API — which must stay pool-free, because
    # `startCommand` runs `uvicorn --workers 2` and every pool booted from the
    # API process runs once per HTTP worker. So the worker tier cannot be
    # declared in this file at all; it needs its own service, which Railway
    # takes from the project settings or from
    # `backend/scripts/deploy_railway.py:205` — a script no CI job runs.
    # Closing this for real means the worker tier's start command reaching a
    # committed artifact Railway reads — a second service config, not an edit to
    # this test.
    "railway": (
        "railway.json can only carry the API service, and the API tier must "
        "start no pool (uvicorn --workers 2 => one copy per HTTP worker). The "
        "worker service exists only in the manual "
        "backend/scripts/deploy_railway.py:205. G-04's external half."
    ),
}


# =========================================================== worker × start ==


def test_every_shipped_worker_has_exactly_one_start_path() -> None:
    """Not zero (a dead feature), not two (a double-started consumer).

    Discovery is structural, so the worker added tomorrow is in this assertion
    before anyone thinks about it.
    """
    paths = _start_paths()
    offenders: list[str] = []

    for cls in sorted(_stream_workers(), key=lambda c: c.__name__):
        found = paths.get(cls.__name__, [])
        recorded = UNDISPATCHED_WORKERS.get(cls.__name__)
        if len(found) == 0 and recorded is None:
            offenders.append(
                f"{cls.__name__} ({cls.__module__}) is started by NOTHING — it is "
                f"dead: add it to POOLS in app/workers/run.py or register a "
                f"scheduler job handler, or record the reason in "
                f"UNDISPATCHED_WORKERS"
            )
        elif len(found) > 1:
            offenders.append(
                f"{cls.__name__} is started TWICE by {found} — two triggers for "
                f"one worker. Keep the one that has a producer."
            )
        elif len(found) == 1 and recorded is not None:
            offenders.append(
                f"{cls.__name__} is recorded as intentionally undispatched but is "
                f"now started by {found[0]} — delete its UNDISPATCHED_WORKERS entry"
            )

    for name, reason in UNDISPATCHED_WORKERS.items():
        cls = _classes_defined_in_workers().get(name)
        if cls is None:
            offenders.append(
                f"UNDISPATCHED_WORKERS names {name!r}, which no longer exists: {reason}"
            )
        elif issubclass(cls, StreamWorker):
            offenders.append(
                f"{name} is a StreamWorker — a stream pool cannot be excused from "
                f"having a start path; register it or delete it"
            )

    assert not offenders, "worker start-path audit failed:\n  " + "\n  ".join(offenders)


@pytest.mark.parametrize("pool", sorted(worker_run.POOLS))
def test_a_pool_name_binds_one_worker_class(pool: str) -> None:
    """``app.workers.run <pool>`` must select one worker, never two.

    Duplicate classes under distinct pool names would let a single process boot
    two consumers of the same stream group with different names.
    """
    cls = worker_run.POOLS[pool]
    twins = [other for other, other_cls in worker_run.POOLS.items() if other_cls is cls]
    assert twins == [pool], (
        f"{cls.__name__} is registered under {twins} — one class, one pool name"
    )
    assert cls.__name__ not in UNDISPATCHED_WORKERS, (
        f"pool:{pool} binds {cls.__name__}, which is recorded as intentionally "
        f"undispatched: the record and the deployment disagree"
    )


def test_the_api_process_starts_no_worker_and_no_relay() -> None:
    """The API must not boot a pool. ``railway.json:8`` runs ``uvicorn
    --workers 2``, so anything started from the app lifespan runs once per HTTP
    worker — two copies claiming the same work inside one deployment.

    Same for the outbox relay: run.py starts it once per worker process, and a
    relay duplicated into the API tier is a duplicated publisher.
    """
    tree = ast.parse(API_MODULE.read_text(encoding="utf-8"), filename=str(API_MODULE))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module
        and not node.level
    }
    used = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}

    worker_imports = {n for n in imported if n.startswith("app.workers")}
    worker_class_names = {cls.__name__ for cls in _stream_workers()} | set(UNDISPATCHED_WORKERS)
    started = sorted(worker_imports | (used & worker_class_names))

    assert not started, (
        f"app/main.py reaches into the worker runtime ({started}). Pools belong "
        f"to `python -m app.workers.run`; uvicorn runs multiple HTTP workers, so "
        f"a pool started here runs one copy per HTTP worker."
    )
    assert "OutboxRelay" not in used, (
        "app/main.py starts the OutboxRelay — the API tier and the worker tier "
        "would then both publish the same outbox rows"
    )


# ======================================================= worker × artifact ===


def _pools_started_by(text: str) -> list[str]:
    """Pool names started by ``python -m app.workers.run ...`` in ``text``.

    No pool arguments means every pool, which is exactly ``run.py``'s argparse
    default. Returned as a list so a start command that names one pool twice is
    still visible to the caller.
    """
    started: list[str] = []
    for line in text.splitlines():
        if WORKER_ENTRYPOINT not in line:
            continue
        tokens = set(re.split(r"[^A-Za-z0-9_.-]+", line)) & set(worker_run.POOLS)
        started.extend(tokens or worker_run.POOLS)
    return started


def _artifact_start_commands() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for artifact in (*DECLARATIVE_ARTIFACTS, *OPERATIONAL_ARTIFACTS):
        if not artifact.is_file():
            continue
        out[str(artifact.relative_to(REPO_ROOT))] = _pools_started_by(
            artifact.read_text(encoding="utf-8")
        )
    return out


def test_every_pool_is_started_by_a_declarative_artifact() -> None:
    """A pool nothing deploys is a feature nobody shipped.

    This is the assertion G-04 can make internally: for every entry in POOLS
    some committed, machine-read deployment file (railway.json / the compose
    stack / a workflow) issues the start command for it. A start command that
    exists only inside a manual provisioning script does not count — nothing
    runs that script, so it proved nothing about deployment.
    """
    commands = _artifact_start_commands()
    declarative = {
        name: pools
        for name, pools in commands.items()
        if pathlib.Path(REPO_ROOT / name) in DECLARATIVE_ARTIFACTS
    }
    covered = {pool for pools in declarative.values() for pool in pools}
    missing = sorted(set(worker_run.POOLS) - covered)

    assert not missing, (
        "pool(s) no declarative artifact starts: "
        + ", ".join(missing)
        + "\nDeclarative artifacts scanned: "
        + ", ".join(sorted(declarative))
        + "\nAdd the start command to a deployment artifact (a service in "
        "infra/docker-compose.yml or a startCommand), not to a script."
    )


def test_no_pool_is_started_twice_in_one_artifact() -> None:
    """Two start commands for one pool = two consumers in one deployment."""
    offenders = [
        f"{artifact} starts pool {pool!r} {count}x"
        for artifact, pools in _artifact_start_commands().items()
        for pool, count in {p: pools.count(p) for p in set(pools)}.items()
        if count > 1
    ]
    assert not offenders, (
        "double-start in one artifact:\n  "
        + "\n  ".join(offenders)
        + "\nOne pool per deployment artifact; scale it with replicas, which the "
        "SKIP LOCKED lease is designed for."
    )


def test_each_topology_starts_every_pool_or_records_why_not() -> None:
    """Per deployment topology, not just per repo.

    ``test_every_pool_is_started_by_a_declarative_artifact`` is a union, so on
    its own it would be satisfied by ONE topology that happens to carry the
    pools while the one actually deployed carries none. This is where the
    honest version of that claim lives: a topology either starts every pool, or
    the gap is written down with a reason here and asserted to still be the gap
    it claims to be.
    """
    offenders: list[str] = []
    for topology, artifacts in DECLARATIVE_TOPOLOGIES.items():
        started = {
            pool
            for artifact in artifacts
            if artifact.is_file()
            for pool in _pools_started_by(artifact.read_text(encoding="utf-8"))
        }
        uncovered = sorted(set(worker_run.POOLS) - started)
        reason = TOPOLOGY_START_GAPS.get(topology)
        if reason is None:
            if uncovered:
                offenders.append(
                    f"topology {topology!r} starts no pool for {uncovered} and "
                    f"records no reason"
                )
        elif not uncovered:
            offenders.append(
                f"topology {topology!r} is recorded as a gap but now starts every "
                f"pool — delete its TOPOLOGY_START_GAPS entry: {reason}"
            )

    bogus = sorted(set(TOPOLOGY_START_GAPS) - set(DECLARATIVE_TOPOLOGIES))
    if bogus:
        offenders.append(
            f"TOPOLOGY_START_GAPS records {bogus}, which is not a topology — "
            f"an excuse nobody can trip"
        )

    assert not offenders, "topology coverage failed:\n  " + "\n  ".join(offenders)


def test_no_api_start_command_hides_a_worker_pool() -> None:
    """``sh -c 'uvicorn app.main:app && python -m app.workers.run'`` is a pool
    that never starts: uvicorn does not return, so the second half of the line
    is unreachable, and the artifact still reads as "the pools are deployed".

    The API and a worker pool are separate processes, which is what the compose
    ``api`` / ``worker`` pair expresses.
    """
    offenders = [
        f"{artifact.relative_to(REPO_ROOT)}:{line_number}: {line.strip()}"
        for artifact in API_ARTIFACTS
        if artifact.is_file()
        for line_number, line in enumerate(
            artifact.read_text(encoding="utf-8").splitlines(), start=1
        )
        if API_ENTRYPOINT in line and WORKER_ENTRYPOINT in line
    ]
    assert not offenders, (
        "start command runs the API and a worker pool on the same line, so the "
        "pool never starts:\n  " + "\n  ".join(offenders)
    )


def test_ci_never_starts_a_worker_pool() -> None:
    """CI runs the test suite, not the product. A workflow that boots a pool
    would put a second copy of every consumer against whatever database the job
    happens to reach."""
    offenders = [
        str(path.relative_to(REPO_ROOT))
        for path in sorted(CI_DIR.glob("*.y*ml"))
        for pool in _pools_started_by(path.read_text(encoding="utf-8"))
    ]
    assert not offenders, f"workflow(s) start worker pools: {sorted(set(offenders))}"


# ======================================================== job types × handler


def _produced_job_types() -> dict[str, str]:
    """job_type literals a ``ScheduledJob`` is created with, across ``app/``.

    Derived from the call sites, not from a list: the scheduler can dispatch
    whatever any producer can enqueue, and a type with no handler is claimed,
    then failed with "no handler for ..." on every poll.
    """
    produced: dict[str, str] = {}
    for path in sorted((BACKEND_ROOT / "app").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            is_scheduled_job = isinstance(func, ast.Name) and func.id == "ScheduledJob"
            is_typed_column_write = (
                isinstance(func, ast.Attribute) and func.attr == "job_type"
            )
            if not (is_scheduled_job or is_typed_column_write):
                continue
            for keyword in node.keywords:
                if keyword.arg == "job_type" and isinstance(keyword.value, ast.Constant):
                    value = keyword.value.value
                    if isinstance(value, str):
                        produced.setdefault(
                            value, f"{path.relative_to(BACKEND_ROOT)}:{node.lineno}"
                        )
    return produced


def test_every_job_type_a_producer_can_enqueue_has_a_handler() -> None:
    """The scheduler's other half: a dispatchable job type must be handled.

    ``SchedulerWorker._drain_tenant`` claims the row, sets ``processing``, then
    writes ``failed / "no handler for <type>"`` — so a producer without a
    handler is not a missing feature, it is a queue that fills with failures.
    """
    handlers = set(scheduler._HANDLERS)  # noqa: SLF001 — the registry is the contract
    unhandled = {
        job_type: where
        for job_type, where in _produced_job_types().items()
        if job_type not in handlers
    }
    assert not unhandled, (
        "job type(s) produced with no scheduler handler:\n  "
        + "\n  ".join(f"{jt} (produced at {where})" for jt, where in sorted(unhandled.items()))
        + "\nRegister one next to the other handlers in "
        "app/workers/scheduler_worker.py, or stop producing the row."
    )


@pytest.mark.parametrize("job_type", sorted(scheduler.RECURRING_JOBS))
def test_every_recurring_job_type_has_a_handler(job_type: str) -> None:
    """``ensure_recurring_jobs`` seeds a row per active tenant for every key of
    ``RECURRING_JOBS``; a key with no handler guarantees that row fails forever.
    """
    assert job_type in scheduler._HANDLERS, (  # noqa: SLF001 — the registry
        f"recurring job {job_type!r} is seeded but has no handler — register one "
        f"with register_job_handler({job_type!r}, ...) in scheduler_worker.py"
    )


def test_every_handler_is_dispatchable() -> None:
    """A handler nothing can invoke is the same orphan in reverse.

    Reachable either as a recurring sweep the scheduler seeds, or as a job_type
    some producer enqueues.
    """
    reachable = set(scheduler.RECURRING_JOBS) | set(_produced_job_types())
    orphans = sorted(set(scheduler._HANDLERS) - reachable)  # noqa: SLF001 — the registry
    assert not orphans, (
        f"scheduler handler(s) nothing ever dispatches: {orphans}. Add a producer "
        f"(RECURRING_JOBS or a ScheduledJob row) or delete the handler."
    )


def test_every_job_kind_the_api_can_queue_has_a_runner() -> None:
    """``jobs`` rows are executed by ``job_runner``, keyed on ``Job.kind``.

    An unregistered kind fails with "no handler registered for job kind", so a
    new kind queued from a route or a sweep must ship with its runner.
    """
    produced: set[str] = set()
    for path in sorted((BACKEND_ROOT / "app").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            creates_job = (isinstance(func, ast.Name) and func.id == "Job") or (
                isinstance(func, ast.Attribute)
                and func.attr == "create"
                and isinstance(func.value, ast.Name)
                and func.value.id == "JobService"
            )
            if not creates_job:
                continue
            for keyword in node.keywords:
                if keyword.arg == "kind" and isinstance(keyword.value, ast.Constant):
                    if isinstance(keyword.value.value, str):
                        produced.add(keyword.value.value)

    unrun = sorted(produced - set(job_runner.registered_job_kinds()))
    assert not unrun, (
        f"job kind(s) with no runner: {unrun}. Register a handler with "
        f"@register_job_handler(kind) in app/workers/job_runner.py — "
        f"JobService.create only queues the row."
    )


# =========================================================== non-vacuity =====


def test_the_detector_actually_distinguishes_started_from_dead() -> None:
    """Proof the discovery + start-path machinery discriminates both ways.

    A guard that reports every worker as started, or none, is worse than no
    guard: it turns green into a claim nobody can read.
    """
    discovered = {cls.__name__ for cls in _stream_workers()}

    # A stream pool a deployment boots: discovered AND registered AND covered.
    assert "MessageWorker" in discovered, "detector missed the message pool"
    paths = _start_paths()
    assert paths.get("MessageWorker") == ["pool:messages"], paths.get("MessageWorker")
    covered = {p for ps in _artifact_start_commands().values() for p in ps}
    assert "messages" in covered, "a start command exists but was not parsed"

    # An operator CLI, not a worker: must NOT show up as a startable pool.
    assert "inspector" not in worker_run.POOLS
    assert not {"list_dlq", "requeue"} & discovered, "the DLQ inspector is not a worker"

    # Global maintenance sweeps are started by SchedulerWorker, outside the
    # tenant-scoped ScheduledJob queue.
    assert "OffboardingWorker" in _classes_defined_in_workers()
    assert paths.get("OffboardingWorker") == ["global_sweep:offboarding.purge"]
    assert "password_reset_email" in scheduler.GLOBAL_SWEEPERS

    # An absent name is not "started": the predicate is not always-true.
    assert not paths.get("WorkerThatDoesNotExist")
