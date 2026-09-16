"""Monitoring: status of nodes, apps, and services; alert surface."""

from __future__ import annotations

from ..config import Config
from .. import runners


def nodes(*, cfg: Config | None = None) -> dict:
    cfg = cfg or Config.load()
    out = runners.kubectl(["get", "nodes", "-o", "wide"])
    return {"nodes": out}


def pods(namespace: str | None = None, *, cfg: Config | None = None) -> dict:
    cfg = cfg or Config.load()
    args = ["get", "pods", "-A"] if namespace is None else ["get", "pods", "-n", namespace]
    args += ["-o", "wide"]
    out = runners.kubectl(args)
    return {"namespace": namespace or "all", "pods": out}


def summary(*, cfg: Config | None = None) -> dict:
    cfg = cfg or Config.load()
    return {
        "nodes": runners.kubectl(["get", "nodes", "--no-headers"]).count("\n") + 1,
        "uptime_kuma": f"http://{cfg.ops_host}:3001",
        "homepage": f"http://{cfg.ops_host}:8080",
    }
