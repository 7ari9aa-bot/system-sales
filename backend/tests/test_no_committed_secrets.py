"""No credential may be committed to the repository.

This repository is public. A real Railway project token once sat in a docs file on ``main``
(docs/RAILWAY_TOKEN_GUIDE.md); removing it from the file does not remove it from git history,
so the only real fix is to stop it happening again. This scans every TRACKED file.

What counts as a secret is deliberately narrow (provider-specific prefixes plus a labelled
assignment) so it does not fire on UUIDs, hashes, or the fake keys the guardrail tests feed to
the redactor on purpose. Those fakes are listed in ALLOWED and each must stay obviously fake.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

PATTERNS = {
    "github token": re.compile(r"\b(?:ghp|gho|ghs|ghu|github_pat)_[A-Za-z0-9_]{30,}"),
    "supabase token": re.compile(r"\bsbp_[0-9a-f]{30,}"),
    "google api key": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    "openai-style key": re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{32,}"),
    "private key block": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |)PRIVATE KEY-----"),
    # a token-named variable assigned a bare UUID/long value: how the Railway one leaked
    "labelled token": re.compile(
        r"""\b[A-Z0-9_]*(?:TOKEN|SECRET|API_KEY|PASSWORD)[A-Z0-9_]*[ \t]*=[ \t]*['"]?"""
        r"""(?!<|\$|\{|your|xxx|changeme|example|placeholder|test|fake|dummy)"""
        r"""[A-Za-z0-9_\-]{24,}['"]?"""
    ),
}

# Fake-on-purpose strings the guardrail tests need. Matching is by exact file, so a real key
# pasted into any other file still fails.
ALLOWED = {
    "backend/tests/test_mfa_login_flow.py",  # RFC 6238 published TOTP test vector
    "backend/tests/test_meta_oauth.py",  # fake app secret for the OAuth tests
    "backend/tests/test_ai_guardrail_coverage.py",
    "backend/tests/test_guardrail_boundary.py",
    "backend/tests/test_no_committed_secrets.py",
}

SKIP_SUFFIXES = (".png", ".jpg", ".jpeg", ".icns", ".ico", ".woff", ".woff2", ".lock", ".gz")


def _tracked() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=REPO, capture_output=True, check=True
    ).stdout
    return [p for p in out.decode().split("\0") if p]


def test_no_credential_is_committed() -> None:
    hits: list[str] = []
    for rel in _tracked():
        if rel in ALLOWED or rel.endswith(SKIP_SUFFIXES):
            continue
        try:
            text = (REPO / rel).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for label, pattern in PATTERNS.items():
            for m in pattern.finditer(text):
                line = text.count("\n", 0, m.start()) + 1
                hits.append(f"{rel}:{line} looks like a {label}")  # never print the value
    assert not hits, "committed credentials (rotate them, then remove):\n" + "\n".join(hits)


def test_the_scanner_would_catch_the_leak_it_exists_for() -> None:
    leaked = "export RAILWAY_TOKEN='1bfbf228-dbc5-4f3c-8820-e02738beedf6'"
    assert PATTERNS["labelled token"].search(leaked)
    assert not PATTERNS["labelled token"].search("export RAILWAY_TOKEN='<RAILWAY_PROJECT_TOKEN>'")
    assert not PATTERNS["labelled token"].search("S3_SECRET_ACCESS_KEY=")
