"""The jobs worker process must know how to run ``import.run``.

Handlers register themselves with a decorator at import time. The API process imported
``app.workers.import_runner`` (through the imports router) but the worker process did not, so a
queued merchant import was claimed and then dropped with ``job_runner.no_handler``. Importing the
module in a fresh interpreter, exactly as ``python -m app.workers.run`` does, must be enough.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap


def test_a_fresh_worker_process_has_the_import_handler():
    code = textwrap.dedent(
        """
        import app.workers.run  # what `python -m app.workers.run` loads
        from app.workers.job_runner import registered_job_kinds
        kinds = registered_job_kinds()
        assert "import.run" in kinds, sorted(kinds)
        print("ok")
        """
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=120, check=False
    )
    assert out.returncode == 0, out.stderr[-800:]
    assert out.stdout.strip().endswith("ok")
