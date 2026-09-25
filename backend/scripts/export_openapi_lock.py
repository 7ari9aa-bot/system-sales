"""Export ``desktop/openapi.lock.json`` from the live application schema (R1).

The desktop team consumes the PUBLISHED schema, pinned in the repository with
the counts and SHA-256 the export measured. Any route change that does not come
with a regenerated lock fails ``tests/test_openapi_lock.py`` in CI.

    python scripts/export_openapi_lock.py          # (re)write the lock
    python scripts/export_openapi_lock.py --check  # exit 1 if it would change
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.openapi_lock import (  # noqa: E402
    LOCK_PATH,
    canonical_json,
    regenerate_lock_document,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit 1 without writing if the committed lock is stale",
    )
    args = parser.parse_args()

    document = regenerate_lock_document()
    full = canonical_json(document)

    if args.check:
        if LOCK_PATH.exists() and LOCK_PATH.read_text(encoding="utf-8") == full:
            measured = document["measured"]
            print(
                f"openapi lock: OK ({measured['operations']} operations, "
                f"{measured['typed_operations']} typed)"
            )
            return 0
        print(f"openapi lock: STALE — {LOCK_PATH} does not match the live schema", file=sys.stderr)
        return 1

    LOCK_PATH.write_text(full, encoding="utf-8", newline="\n")
    # The spec body is written inside `full`; the measure line below repeats the
    # counts so the generating run is greppable in CI logs.
    measured = document["measured"]
    print(
        f"openapi lock: wrote {LOCK_PATH} "
        f"({measured['operations']} operations, {measured['typed_operations']} typed, "
        f"sha256 {measured['sha256'][:16]}…)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
