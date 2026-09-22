"""Tunnel exposure abstraction (provider registry).

A tunnel provider owns a small verb set for exposing a home backend through a
public host: list routes, upsert (add/point a route), delete a route, report
status, and verify from a public vantage. The registry maps the
OPSLAYER_TUNNEL_PROVIDER setting to an implementation; everything above this
layer (CLI, MCP, agents) is provider-agnostic, so a Cloudflare provider can
replace frp later without touching callers.

Implementations live in sibling modules and register themselves here.

    Adding a provider (cloudflare, ...):
        1. subclass the verb set implemented by siblings
        2. implement the verbs (return plain JSON-able dicts)
        3. @register("provider-name")
        4. set OPSLAYER_TUNNEL_PROVIDER in .env (default "frp")
"""

from __future__ import annotations

from typing import Protocol

_PROVIDERS: dict[str, type["TunnelProvider"]] = {}


class TunnelProvider(Protocol):
    def list_routes(self, *, cfg) -> dict: ...
    def upsert_route(self, name: str, target: str, domains: list[str] | None, *, cfg) -> dict: ...
    def delete_route(self, name: str, *, cfg) -> dict: ...
    def status(self, *, cfg) -> dict: ...
    def verify(self, public_url: str, *, cfg) -> dict: ...


def register(name: str):
    def decorator(cls: type[TunnelProvider]) -> type[TunnelProvider]:
        _PROVIDERS[name] = cls
        return cls

    return decorator


def get_provider(name: str | None = None, cfg=None) -> TunnelProvider:
    from ...config import get_config

    selected = name
    if not selected:
        try:
            selected = get_config().tunnel_provider
        except (RuntimeError, AttributeError):
            selected = None
    if not selected:
        selected = "frp"
    if selected not in _PROVIDERS:
        raise LookupError(
            f"unknown tunnel provider: {selected!r}; available: {sorted(_PROVIDERS)}"
        )
    return _PROVIDERS[selected](cfg)


def available_providers() -> list[str]:
    return sorted(_PROVIDERS)


# Providers register at the bottom so the registry is defined first.
from . import frp as _frp  # noqa: E402,F401