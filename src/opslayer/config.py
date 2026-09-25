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
import re
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
    "OPSLAYER_MONITOR_SSH_USER": "monitor_ssh_user",
    "OPSLAYER_GATUS_PORT": "gatus_port",
    "OPSLAYER_NUT_EXPORTER_PORT": "nut_exporter_port",
    "OPSLAYER_ARGOCD_URL": "argocd_url",
    "OPSLAYER_ARGOCD_API_KEY": "argocd_api_key",
    "OPSLAYER_MONITOR_ENDPOINTS": "monitor_endpoints",
    "OPSLAYER_BESZEL_KEY": "beszel_key",
    "OPSLAYER_BESZEL_TOKEN": "beszel_token",
    "OPSLAYER_BESZEL_HUB_URL": "beszel_hub_url",
    "OPSLAYER_BESZEL_PORT": "beszel_port",
    "OPSLAYER_BESZEL_ADMIN_EMAIL": "beszel_admin_email",
    "OPSLAYER_BESZEL_ADMIN_PASSWORD": "beszel_admin_password",
}

WRITABLE_KEYS = frozenset(_ATTR_BY_ENV.values()) | {"backup_root"}
# map CLI-facing attribute name -> the OPSLAYER_* key actually written to .env
_ENV_BY_ATTR = {attr: env for env, attr in _ATTR_BY_ENV.items()}
_ENV_BY_ATTR["backup_root"] = "OPSLAYER_BACKUP_ROOT"


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
    monitor_ssh_user: str = "solvire"
    gatus_port: int = 8080
    nut_exporter_port: int = 9199
    argocd_url: str = ""
    argocd_api_key: str = ""
    monitor_endpoints: str = ""
    beszel_key: str = ""
    beszel_token: str = ""
    beszel_hub_url: str = "http://127.0.0.1:8090"
    beszel_port: int = 8090
    beszel_admin_email: str = ""
    beszel_admin_password: str = ""
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
        for port_key, env_name in (
            ("gatus_port", "OPSLAYER_GATUS_PORT"),
            ("nut_exporter_port", "OPSLAYER_NUT_EXPORTER_PORT"),
            ("beszel_port", "OPSLAYER_BESZEL_PORT"),
        ):
            if port_key in values:
                try:
                    values[port_key] = int(values[port_key])
                except ValueError:
                    raise ValueError(f"{env_name} must be an integer")
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


def _format_env_value(value: str) -> str:
    """Quote only when the value would otherwise not round-trip as one token."""
    if value == "" or any(ch.isspace() for ch in value) or "#" in value:
        return '"' + value.replace('"', '\\"') + '"'
    return value


def _set_env_line(env_key: str, value: str) -> None:
    """Update one key in .env IN PLACE, preserving every other line verbatim.

    Never rewrites the whole file: comments, blank lines, ordering, unrelated
    keys (AWS creds, etc.) and their formatting are left untouched. Replaces the
    first matching line, otherwise appends under a separating blank line.
    """
    pattern = re.compile(rf"^\s*(?:export\s+)?{re.escape(env_key)}\s*=")
    rendered = f"{env_key}={_format_env_value(value)}"
    lines = _ENV_FILE.read_text(encoding="utf-8").splitlines() if _ENV_FILE.exists() else []
    for i, line in enumerate(lines):
        if pattern.match(line):
            lines[i] = rendered
            break
    else:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(rendered)
    _ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _remove_env_line(env_key: str) -> bool:
    pattern = re.compile(rf"^\s*(?:export\s+)?{re.escape(env_key)}\s*=")
    if not _ENV_FILE.exists():
        return False
    lines = _ENV_FILE.read_text(encoding="utf-8").splitlines()
    kept = [line for line in lines if not pattern.match(line)]
    if len(kept) == len(lines):
        return False
    _ENV_FILE.write_text("\n".join(kept) + "\n", encoding="utf-8")
    return True


def set_value(key: str, value: str) -> dict:
    """Persist one value to the repo-root .env under its OPSLAYER_* key.

    `key` is the CLI-facing attribute name (e.g. "ops_host") OR the OPSLAYER_*
    env name; either resolves to the same .env key so Config.load() reads it.
    Only that one line is touched - the rest of the file is never rewritten.
    """
    if key not in WRITABLE_KEYS:
        raise ValueError(f"unknown or non-writable key: {key}; writable: {sorted(WRITABLE_KEYS)}")
    env_key = _ENV_BY_ATTR[key]
    _set_env_line(env_key, value)
    return {"set": env_key, "path": str(_ENV_FILE)}


def unset_value(key: str) -> dict:
    if key not in WRITABLE_KEYS:
        raise ValueError(f"unknown or non-writable key: {key}")
    env_key = _ENV_BY_ATTR[key]
    if not _remove_env_line(env_key):
        return {"unset": env_key, "result": "not set"}
    return {"unset": env_key, "path": str(_ENV_FILE)}


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
