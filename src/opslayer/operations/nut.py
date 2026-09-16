"""Power: NUT queries against the pihole Zero's NUT server.

upsc returns `key: value` lines. This module parses them into a typed view:
power state (online/on battery/low battery), charge, load, runtime, and the
raw values for anything unmodeled.
"""

from __future__ import annotations

from ..config import Config
from ..events import record
from .. import runners

# ups.status is a space-separated flag string; NUT defines these flags.
_STATUS_FLAGS = {
    "OL": "online",
    "OB": "on battery",
    "LB": "low battery",
    "HB": "high battery",
    "RB": "replace battery",
    "CHRG": "charging",
    "DISCHRG": "discharging",
    "BYPASS": "bypass active",
    "CAL": "calibrating",
    "OFF": "ups off",
    "OVER": "overloaded",
    "TRIM": "trimming voltage",
    "BOOST": "boosting voltage",
    "FSD": "forced shutdown",
}


def _target(cfg: Config) -> str:
    return f"{cfg.nut_ups_name}@{cfg.nut_server}"


def _raw_values(cfg: Config) -> dict[str, str]:
    out = runners.upsc(_target(cfg))
    values: dict[str, str] = {}
    for line in out.splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            values[key.strip()] = value.strip()
    return values


def _parse_status(raw: str) -> dict:
    flags = raw.split()
    return {
        "raw": raw,
        "state": _STATUS_FLAGS.get(flags[0], f"unknown({flags[0]})") if flags else "unknown",
        "online": "OL" in flags,
        "on_battery": "OB" in flags,
        "low_battery": "LB" in flags,
        "replace_battery": "RB" in flags,
        "charging": "CHRG" in flags,
        "discharging": "DISCHRG" in flags,
    }


def _as_int(value: str | None) -> int | None:
    try:
        return int(float(value)) if value is not None else None
    except ValueError:
        return None


def _as_float(value: str | None) -> float | None:
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


def status(*, cfg: Config | None = None) -> dict:
    cfg = cfg or Config.load()
    values = _raw_values(cfg)
    result = {
        "ups": _target(cfg),
        "model": values.get("device.model") or values.get("ups.model"),
        "status": _parse_status(values.get("ups.status", "")),
        "battery_charge_percent": _as_float(values.get("battery.charge")),
        "battery_runtime_seconds": _as_int(values.get("battery.runtime")),
        "load_percent": _as_float(values.get("ups.load")),
        "input_voltage": _as_float(values.get("input.voltage")),
        "battery_mfr_date": values.get("battery.mfr.date"),
        "raw": values,
    }
    if result["status"]["on_battery"]:
        record("nut.observed", result["ups"], "on_battery", {"charge": result["battery_charge_percent"]})
    return result


def get(variable: str, *, cfg: Config | None = None) -> dict:
    cfg = cfg or Config.load()
    out = runners.upsc(_target(cfg), variable)
    return {"ups": _target(cfg), "variable": variable, "value": out}


def compact(*, cfg: Config | None = None) -> dict:
    """Compact one-liner for dashboards: homepage widget / agent glance."""
    full = status(cfg=cfg)
    s = full["status"]
    runtime = full["battery_runtime_seconds"]
    return {
        "ups": full["ups"],
        "power": "on-battery" if s["on_battery"] else "online",
        "alerts": [flag for flag, on in (
            ("low-battery", s["low_battery"]),
            ("replace-battery", s["replace_battery"]),
            ("discharging", s["discharging"]),
        ) if on],
        "charge_percent": full["battery_charge_percent"],
        "load_percent": full["load_percent"],
        "runtime_minutes": round(runtime / 60, 1) if runtime is not None else None,
    }
