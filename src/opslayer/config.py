"""Targets, environments, and defaults. Nothing else hardcodes an address.

Standard 12-factor layout: one .env at the repo root, loaded via python-dotenv.
Precedence (highest wins):
  1. real environment variables (OPSLAYER_*; for CI/agents)
  2. repo-root .env (gitignored; personal values live here)
  3. sensible defaults

Secret/privacy rule: this repo is public. No LAN addresses, credentials, or
topology names in source. Only .env.example is committed; the safety net is
.gitignore + the detect-secrets gate in the test run. Nothing sensitive beyond
LAN topology belongs in .env anyway - real credentials go to sops later.

Write config with the CLI: opslayer config set <key> <value>
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, fields
from pathlib import Path

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ENV_FILE = _REPO_ROOT / ".env"

_ATTR_BY_ENV = {
    "OPSLAYER_OPS_HOST": "ops_host",
    "OPSLAYER_CLUSTER_API": "cluster_api",
    "OPSLAYER_NUT_SERVER": "nut_server",
    "OPSLAYER_NUT_UPS_NAME": "nut_ups_name",
    "OPSLAYER_PIHOLE_HOST": "pihole_host",
    "OPSLAYER_TRUENAS_HOST": "truenas_host",
    "OPSLAYER_DNS_ZONE": "dns_zone",
    "OPSLAYER_DNS_PROVIDER": "dns_provider",
    "OPSLAYER_TUNNEL_PROVIDER": "tunnel_provider",
    "OPSLAYER_FRP_SERVER": "frp_server",
    "OPSLAYER_FRP_TOKEN": "frp_token",
    "OPSLAYER_FRP_PORT": "frp_port",
}

WRITABLE_KEYS = frozenset(_ATTR_BY_ENV.values()) | {"backup_root"}


@dataclass(frozen=True)
class Config:
    ops_host: str = ""
    cluster_api: str = ""
    nut_server: str = ""
    nut_ups_name: str = "ups"
    pihole_host: str = ""
    truenas_host: str = ""
    dns_zone: str = ""
    dns_provider: str = "route53"
    tunnel_provider: str = "frp"
    frp_server: str = ""
    frp_token: str = ""
    frp_port: int = 7000
    backup_root: Path = field(default_factory=lambda: Path("/srv/backups"))
    json_output: bool = False

    @classmethod
    def load(cls) -> "Config":
        load_dotenv(_ENV_FILE, override=False)
        values: dict = {}
        for env_key, attr in _ATTR_BY_ENV.items():
            if os.environ.get(env_key):
                values[attr] = os.environ[env_key]
        if os.environ.get("OPSLAYER_BACKUP_ROOT"):
            values["backup_root"] = Path(os.environ["OPSLAYER_BACKUP_ROOT"])
        if "frp_port" in values:
            try:
                values["frp_port"] = int(values["frp_port"])
            except ValueError:
                raise ValueError("OPSLAYER_FRP_PORT must be an integer")
        return cls(**{**cls().__dict__, **values})


def env_path() -> Path:
    return _ENV_FILE


def _read_env() -> dict[str, str]:
    values: dict[str, str] = {}
    if not _ENV_FILE.exists():
        return values
    for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip("'\"")
    return values


def _write_env(data: dict[str, str]) -> None:
    lines = [f"{key}={data[key]}" for key in sorted(data)]
    _ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def set_value(key: str, value: str) -> dict:
    if key not in WRITABLE_KEYS:
        raise ValueError(f"unknown or non-writable key: {key}; writable: {sorted(WRITABLE_KEYS)}")
    data = _read_env()
    data[key] = value
    _write_env(data)
    return {"set": key, "value": value, "path": str(_ENV_FILE)}


def unset_value(key: str) -> dict:
    if key not in WRITABLE_KEYS:
        raise ValueError(f"unknown or non-writable key: {key}")
    data = _read_env()
    if key not in data:
        return {"unset": key, "result": "not set"}
    del data[key]
    _write_env(data)
    return {"unset": key, "path": str(_ENV_FILE)}


def get_config() -> Config:
    cfg = Config.load()
    missing = [k for k in ("ops_host", "cluster_api", "nut_server") if not getattr(cfg, k)]
    if missing:
        raise RuntimeError(
            f"opslayer is not configured; missing {', '.join(missing)}. "
            f"Run: opslayer config set <key> <value> (or set OPSLAYER_* env vars)."
        )
    return cfg


def field_names() -> list[str]:
    return [f.name for f in fields(Config)]
