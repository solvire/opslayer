"""Node lifecycle: drain, cordon, uncordon, reboot coordination."""

from __future__ import annotations

from ..config import Config
from ..events import record
from .. import runners


def cordon(node: str, *, cfg: Config | None = None) -> dict:
    cfg = cfg or Config.load()
    out = runners.kubectl(["cordon", node])
    entry = record("cluster.cordon", node, "ok")
    return {"result": "ok", "node": node, "output": out, "event": entry}


def uncordon(node: str, *, cfg: Config | None = None) -> dict:
    cfg = cfg or Config.load()
    out = runners.kubectl(["uncordon", node])
    entry = record("cluster.uncordon", node, "ok")
    return {"result": "ok", "node": node, "output": out, "event": entry}


def drain(node: str, *, ignore_daemonsets: bool = True, cfg: Config | None = None) -> dict:
    cfg = cfg or Config.load()
    args = ["drain", node, "--delete-emptydir-data"]
    if ignore_daemonsets:
        args.append("--ignore-daemonsets")
    out = runners.kubectl(args, timeout=300)
    entry = record("cluster.drain", node, "ok")
    return {"result": "ok", "node": node, "output": out, "event": entry}
