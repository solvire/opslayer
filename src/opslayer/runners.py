"""Subprocess wrappers for external tools. opslayer orchestrates, never reimplements."""

from __future__ import annotations

import shutil
import subprocess


class OpError(RuntimeError):
    pass


def run(cmd: list[str], *, timeout: int = 60, check: bool = True) -> str:
    binary = shutil.which(cmd[0])
    if binary is None:
        raise OpError(f"required tool not found: {cmd[0]}")
    proc = subprocess.run(
        [binary, *cmd[1:]],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if check and proc.returncode != 0:
        raise OpError(f"{cmd[0]} failed ({proc.returncode}): {proc.stderr.strip() or proc.stdout.strip()}")
    return proc.stdout.strip()


def kubectl(args: list[str], *, timeout: int = 60) -> str:
    return run(["kubectl", *args], timeout=timeout)


def argocd(args: list[str], *, timeout: int = 120) -> str:
    return run(["argocd", *args], timeout=timeout)


def restic(args: list[str], *, timeout: int = 3600) -> str:
    return run(["restic", *args], timeout=timeout)


def upsc(ups: str, var: str | None = None, *, timeout: int = 15) -> str:
    args = ["upsc", ups] + ([var] if var else [])
    return run(args, timeout=timeout)
