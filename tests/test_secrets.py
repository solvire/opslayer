"""Secret-scan gate: detect-secrets must be clean against the baseline.

Runs as part of pytest - not a git hook (the operator declined hooks).
Skip with: pytest -k "not secrets"
"""

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _detect_secrets() -> str | None:
    from shutil import which

    return which("detect-secrets")


@pytest.mark.skipif(_detect_secrets() is None, reason="detect-secrets not installed")
def test_no_new_secrets() -> None:
    result = subprocess.run(
        [
            "detect-secrets",
            "scan",
            "--baseline",
            str(REPO_ROOT / ".secrets.baseline"),
            "--exclude-files",
            r"\.venv/",
            "--exclude-files",
            r"__pycache__/",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    leaked = [line for line in result.stdout.splitlines() if '"results"' not in line and '"hashed_secret"' in line]
    assert not leaked, f"new secrets detected:\n" + "\n".join(leaked)
