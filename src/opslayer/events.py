"""Append-only event log for every opslayer action."""

from __future__ import annotations

import json
import os
import socket
from datetime import datetime, timezone
from pathlib import Path

_EVENT_ROOT = Path(
    os.environ.get("OPSLAYER_EVENT_LOG", Path.home() / ".local/state/opslayer/events.jsonl")
)


def record(event: str, target: str, result: str, detail: dict | None = None) -> dict:
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "host": socket.gethostname(),
        "event": event,
        "target": target,
        "result": result,
        "detail": detail or {},
    }
    _EVENT_ROOT.parent.mkdir(parents=True, exist_ok=True)
    with _EVENT_ROOT.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")
    return entry


def tail(limit: int = 20) -> list[dict]:
    if not _EVENT_ROOT.exists():
        return []
    lines = _EVENT_ROOT.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines[-limit:]]
