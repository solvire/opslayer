"""Secrets: sops encrypt/decrypt status. Credentials never enter this repo."""

from __future__ import annotations

from pathlib import Path

from ..config import Config
from ..events import record
from .. import runners


def encrypt_file(path: Path, *, in_place: bool = True) -> dict:
    cfg = Config.load()
    args = ["sops", "--encrypt", "--in-place"] if in_place else ["sops", "--encrypt"]
    if not in_place:
        raise NotImplementedError("output-to-stdout mode lands with the first real consumer")
    out = runners.run([*args, str(path)], timeout=60)
    entry = record("secrets.encrypt", str(path), "ok")
    return {"result": "ok", "path": str(path), "output": out, "event": entry}


def decrypt_file(path: Path, *, to_stdout: bool = True) -> dict:
    if not to_stdout:
        raise ValueError("decrypt-to-file is intentionally unsupported; pipe to the consumer")
    out = runners.run(["sops", "--decrypt", str(path)], timeout=60)
    return {"path": str(path), "secret": out}


def status(paths: list[Path], *, cfg: Config | None = None) -> dict:
    return {
        "paths": [
            {"path": str(p), "is_sops_encrypted": "sops" in p.read_text(encoding="utf-8")[:2048]}
            for p in paths
            if p.exists()
        ]
    }
