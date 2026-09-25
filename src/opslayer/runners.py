"""Subprocess wrappers for external tools. opslayer orchestrates, never reimplements."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class OpError(RuntimeError):
    pass


def run(cmd: list[str], *, timeout: int = 60, check: bool = True, input: str | None = None) -> str:
    binary = shutil.which(cmd[0])
    if binary is None:
        raise OpError(f"required tool not found: {cmd[0]}")
    proc = subprocess.run(
        [binary, *cmd[1:]],
        input=input,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if check and proc.returncode != 0:
        raise OpError(f"{cmd[0]} failed ({proc.returncode}): {proc.stderr.strip() or proc.stdout.strip()}")
    return proc.stdout.strip()


def ssh(user: str, host: str, command: str, *, timeout: int = 60) -> str:
    """Run a remote command over SSH (the operator-sanctioned remote channel)."""
    return run(["ssh", "-o", "BatchMode=yes", f"{user}@{host}", command], timeout=timeout)


def remote_status(user: str, host: str, command: str, *, timeout: int = 60) -> tuple[int, str]:
    """Run a remote command without raising; returns (returncode, stdout).

    For probes and checks where a nonzero exit is data, not an error.
    """
    binary = shutil.which("ssh")
    if binary is None:
        raise OpError("required tool not found: ssh")
    proc = subprocess.run(
        [binary, "-o", "BatchMode=yes", f"{user}@{host}", command],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    return proc.returncode, proc.stdout.strip()


def remote_write(user: str, host: str, remote_path: str, content: str, *, timeout: int = 60) -> str:
    """Write content to a remote file over SSH without leaking it to the local shell.

    Content is piped via stdin to `tee`, so it never appears in ps or history.
    """
    return run(
        ["ssh", "-o", "BatchMode=yes", f"{user}@{host}", f"sudo tee {remote_path} > /dev/null"],
        input=content,
        timeout=timeout,
    )


def remote_systemctl(user: str, host: str, action: str, unit: str, *, timeout: int = 60) -> str:
    """Run a systemctl action on a remote host (start/stop/enable/status/etc)."""
    return ssh(user, host, f"sudo systemctl {action} {unit}", timeout=timeout)


def kubectl(args: list[str], *, timeout: int = 60, input: str | None = None) -> str:
    return run(["kubectl", *args], timeout=timeout, input=input)


def argocd(args: list[str], *, timeout: int = 120) -> str:
    return run(["argocd", *args], timeout=timeout)


def restic(args: list[str], *, timeout: int = 3600) -> str:
    return run(["restic", *args], timeout=timeout)


def upsc(ups: str, var: str | None = None, *, timeout: int = 15) -> str:
    args = ["upsc", ups] + ([var] if var else [])
    return run(args, timeout=timeout)
