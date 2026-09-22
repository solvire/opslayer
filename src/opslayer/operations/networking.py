"""Networking: DNS (pluggable provider) and ingress.

DNS verbs dispatch through the provider registry (see dns/__init__.py).
OPSLAYER_DNS_PROVIDER selects the backend; default route53.

Tunnel verbs dispatch through the tunnel registry (see tunnel/__init__.py).
OPSLAYER_TUNNEL_PROVIDER selects the backend; default frp.
"""

from __future__ import annotations

from ..config import Config
from .. import runners
from .dns import get_provider
from .tunnel import get_provider as get_tunnel_provider


def list_zones(*, cfg: Config | None = None) -> dict:
    return get_provider(cfg=cfg).list_zones()


def dns_list(zone: str | None = None, *, cfg: Config | None = None) -> dict:
    return get_provider(cfg=cfg).list_records(zone)


def dns_lookup(name: str, *, cfg: Config | None = None) -> dict:
    return get_provider(cfg=cfg).resolve(name)


def dns_upsert(name: str, address: str, record_type: str | None = None, ttl: int = 300, *, cfg: Config | None = None) -> dict:
    return get_provider(cfg=cfg).upsert(name, address, record_type, ttl)


def dns_delete(name: str, record_type: str = "A", *, cfg: Config | None = None) -> dict:
    return get_provider(cfg=cfg).delete(name, record_type)


def ingress_list(namespace: str = "default", *, cfg: Config | None = None) -> dict:
    out = runners.kubectl(["get", "ingress", "-n", namespace, "-o", "wide"])
    return {"namespace": namespace, "ingress": out}


def tunnel_list(*, cfg: Config | None = None) -> dict:
    return get_tunnel_provider(cfg=cfg).list_routes(cfg=cfg)


def tunnel_upsert(
    name: str,
    target: str,
    domains: list[str] | None = None,
    *,
    cfg: Config | None = None,
    rewrite_host: str | None = None,
) -> dict:
    return get_tunnel_provider(cfg=cfg).upsert_route(
        name, target, domains, cfg=cfg, rewrite_host=rewrite_host
    )


def tunnel_delete(name: str, *, cfg: Config | None = None) -> dict:
    return get_tunnel_provider(cfg=cfg).delete_route(name, cfg=cfg)


def tunnel_status(*, cfg: Config | None = None) -> dict:
    return get_tunnel_provider(cfg=cfg).status(cfg=cfg)


def tunnel_verify(public_url: str, *, cfg: Config | None = None) -> dict:
    return get_tunnel_provider(cfg=cfg).verify(public_url, cfg=cfg)
