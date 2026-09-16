"""Backup, restore, drills, housekeeping."""

from __future__ import annotations

from ..config import Config
from ..events import record
from .. import runners


def backup(tags: list[str] | None = None, *, cfg: Config | None = None) -> dict:
    cfg = cfg or Config.load()
    args = ["backup", str(cfg.backup_root)]
    for tag in tags or []:
        args += ["--tag", tag]
    out = runners.restic(args)
    entry = record("maintenance.backup", str(cfg.backup_root), "ok")
    return {"result": "ok", "output": out, "event": entry}


def snapshots(limit: int = 10, *, cfg: Config | None = None) -> dict:
    cfg = cfg or Config.load()
    out = runners.restic(["snapshots", "--latest", str(limit)])
    return {"snapshots": out}


def restore_check(snapshot_id: str, target: str, *, cfg: Config | None = None) -> dict:
    """Drill step: restore a snapshot to a scratch target. Monthly drill is the rule."""
    cfg = cfg or Config.load()
    out = runners.restic(["restore", snapshot_id, "--target", target])
    entry = record("maintenance.restore_drill", snapshot_id, "ok", {"target": target})
    return {"result": "ok", "snapshot": snapshot_id, "target": target, "output": out, "event": entry}
