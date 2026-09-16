"""DNS provider abstraction.

A provider owns four verbs: list zones, list records, upsert a record,
resolve a name. The registry maps the OPSLAYER_DNS_PROVIDER setting to an
implementation; everything above this layer (CLI, MCP, agents) is
provider-agnostic.

Implementations live in sibling modules and register themselves here.
Adding a provider (Cloudflare, PowerDNS, deSEC, ...):

    1. subclass DNSProvider
    2. implement the four verbs (return plain JSON-able dicts)
    3. @register("provider-name")
    4. set OPSLAYER_DNS_PROVIDER in .env
"""

from __future__ import annotations

from typing import Protocol

_PROVIDERS: dict[str, type["DNSProvider"]] = {}


class DNSProvider(Protocol):
    def list_zones(self) -> dict: ...
    def list_records(self, zone: str | None) -> dict: ...
    def upsert(self, name: str, address: str, record_type: str, ttl: int) -> dict: ...
    def resolve(self, name: str) -> dict: ...


def register(name: str):
    def decorator(cls: type[DNSProvider]) -> type[DNSProvider]:
        _PROVIDERS[name] = cls
        return cls

    return decorator


def get_provider(name: str | None = None, cfg=None) -> DNSProvider:
    from ...config import get_config

    selected = name
    if not selected:
        try:
            selected = get_config().dns_provider
        except (RuntimeError, AttributeError):
            selected = None
    if not selected:
        selected = "route53"
    if selected not in _PROVIDERS:
        raise LookupError(
            f"unknown DNS provider: {selected!r}; available: {sorted(_PROVIDERS)}"
        )
    return _PROVIDERS[selected](cfg)  # type: ignore[call-arg]


def available_providers() -> list[str]:
    return sorted(_PROVIDERS)


# Built-in providers import at the bottom so the registry is defined first.
from . import route53 as _route53  # noqa: E402,F401
