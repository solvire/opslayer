"""App deploys: manifest bumps and ArgoCD sync/rollback."""

from __future__ import annotations

from ..config import Config
from ..events import record
from .. import runners


def sync(app: str, *, cfg: Config | None = None, wait: bool = True) -> dict:
    cfg = cfg or Config.load()
    args = ["app", "sync", app]
    if wait:
        args.append("--wait")
    out = runners.argocd(args)
    entry = record("deploy.sync", app, "ok")
    return {"result": "ok", "app": app, "output": out, "event": entry}


def rollback(app: str, revision: str, *, cfg: Config | None = None) -> dict:
    cfg = cfg or Config.load()
    out = runners.argocd(["app", "rollback", app, revision])
    entry = record("deploy.rollback", app, "ok", {"revision": revision})
    return {"result": "ok", "app": app, "revision": revision, "output": out, "event": entry}


def history(app: str, *, cfg: Config | None = None) -> dict:
    cfg = cfg or Config.load()
    out = runners.argocd(["app", "history", app])
    return {"app": app, "history": out}


def status(app: str, *, cfg: Config | None = None) -> dict:
    cfg = cfg or Config.load()
    out = runners.argocd(["app", "get", app, "-o", "json"])
    return {"app": app, "raw": out}
