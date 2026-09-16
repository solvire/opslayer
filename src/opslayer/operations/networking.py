"""Networking: DNS records (Route53), ingress, routing.

Local-name convention: everything on the LAN gets a record under the public
zone (e.g. ops01.<zone> -> 192.168.x.x). RFC 1918 targets in a public zone
are safe - they are unroutable from the internet and the names enumerate
nothing a remote attacker can use.
"""

from __future__ import annotations

import json

from ..config import Config
from ..events import record
from .. import runners


def _zone_id(zone: str | None, cfg: Config) -> str:
    if zone:
        return zone
    name = cfg.dns_zone
    out = runners.run(["aws", "route53", "list-hosted-zones", "--output", "json"], timeout=30)
    zones = json.loads(out)["HostedZones"]
    matches = [z for z in zones if z["Name"].rstrip(".") == name]
    if not matches:
        raise LookupError(f"no hosted zone found for {name}")
    return matches[0]["Id"].split("/")[-1]


def _record_summary(records: list[dict]) -> list[dict]:
    summaries = []
    for r in records:
        summaries.append(
            {
                "name": r["Name"].rstrip("."),
                "type": r["Type"],
                "ttl": r.get("TTL"),
                "values": r.get("ResourceRecords", []),
                "alias": "AliasTarget" in r,
            }
        )
    return summaries


def list_zones(*, cfg: Config | None = None) -> dict:
    cfg = cfg or Config.load()
    out = runners.run(["aws", "route53", "list-hosted-zones", "--output", "json"], timeout=30)
    zones = [
        {"id": z["Id"].split("/")[-1], "name": z["Name"].rstrip("."), "records": z["ResourceRecordSetCount"]}
        for z in json.loads(out)["HostedZones"]
    ]
    return {"zones": zones}


def dns_list(zone: str | None = None, *, cfg: Config | None = None) -> dict:
    cfg = cfg or Config.load()
    zone_id = _zone_id(zone, cfg)
    records: list[dict] = []
    paginator_args = ["aws", "route53", "list-resource-record-sets", "--hosted-zone-id", zone_id, "--output", "json"]
    out = runners.run(paginator_args, timeout=60)
    payload = json.loads(out)
    records.extend(payload.get("ResourceRecordSets", []))
    while payload.get("IsTruncated"):
        payload = json.loads(
            runners.run(
                paginator_args
                + [
                    "--start-record-name",
                    payload["NextRecordName"],
                    "--start-record-type",
                    payload["NextRecordType"],
                ],
                timeout=60,
            )
        )
        records.extend(payload.get("ResourceRecordSets", []))
    return {"zone_id": zone_id, "records": _record_summary(records)}


def dns_lookup(name: str, *, cfg: Config | None = None) -> dict:
    cfg = cfg or Config.load()
    out = runners.run(["dig", "+short", name], timeout=15)
    return {"name": name, "resolved": out.split()}


def dns_upsert(name: str, address: str, record_type: str = "A", ttl: int = 300, *, cfg: Config | None = None) -> dict:
    """Create or update one record. LAN-name convention: bare name under the zone."""
    cfg = cfg or Config.load()
    zone_id = _zone_id(None, cfg)
    fqdn = name if name.endswith(f".{cfg.dns_zone}") else f"{name}.{cfg.dns_zone}"
    change = {
        "Comment": f"opslayer upsert {fqdn}",
        "Changes": [
            {
                "Action": "UPSERT",
                "ResourceRecordSet": {
                    "Name": fqdn,
                    "Type": record_type,
                    "TTL": ttl,
                    "ResourceRecords": [{"Value": address}],
                },
            }
        ],
    }
    out = runners.run(
        [
            "aws",
            "route53",
            "change-resource-record-sets",
            "--hosted-zone-id",
            zone_id,
            "--change-batch",
            json.dumps(change),
            "--output",
            "json",
        ],
        timeout=60,
    )
    entry = record("networking.dns_upsert", fqdn, "ok", {"address": address, "type": record_type})
    return {"result": "ok", "fqdn": fqdn, "address": address, "output": out, "event": entry}
