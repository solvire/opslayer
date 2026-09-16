import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"


def test_cli_help():
    result = subprocess.run(
        [sys.executable, "-m", "opslayer.cli", "--help"],
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(SRC), "PATH": "/usr/bin:/bin"},
    )
    assert result.returncode == 0
    assert "Control layer" in result.stdout
