"""Networking: DNS records (Route53 local names), ingress, routing."""

from __future__ import annotations

from ..config import Config
from ..events import record
from .. import runners


def dns_records(zone: str, *, cfg: Config | None = None) -> dict:
    cfg = cfg or Config.load()
    zone_id = zone or cfg.dns_zone
    out = runners.run(
        ["aws", "route53", "list-resource-record-sets", "--hosted-zone-id", zone_id, "--output", "json"],
        timeout=30,
    )
    return {"zone": zone_id, "raw": out}


def ingress_list(namespace: str = "default", *, cfg: Config | None = None) -> dict:
    cfg = cfg or Config.load()
    out = runners.kubectl(["get", "ingress", "-n", namespace, "-o", "wide"])
    return {"namespace": namespace, "ingress": out}
