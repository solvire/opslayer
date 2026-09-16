"""AWS Route53 provider."""

from __future__ import annotations

import json

from ...config import Config
from ...events import record
from ... import runners
from . import register


def _run(args: list[str], timeout: int = 60) -> str:
    return runners.run(["aws", *args], timeout=timeout)


@register("route53")
class Route53Provider:
    def __init__(self, cfg: Config | None = None):
        self.cfg = cfg or Config.load()

    def list_zones(self) -> dict:
        out = _run(["route53", "list-hosted-zones", "--output", "json"], timeout=30)
        zones = [
            {
                "id": z["Id"].split("/")[-1],
                "name": z["Name"].rstrip("."),
                "records": z["ResourceRecordSetCount"],
            }
            for z in json.loads(out)["HostedZones"]
        ]
        return {"zones": zones}

    def _zone_id(self, zone: str | None) -> str:
        if zone:
            return zone
        name = self.cfg.dns_zone
        zones = self.list_zones()["zones"]
        matches = [z for z in zones if z["name"] == name]
        if not matches:
            raise LookupError(f"no hosted zone found for {name}")
        return matches[0]["id"]

    def list_records(self, zone: str | None = None) -> dict:
        zone_id = self._zone_id(zone)
        records: list[dict] = []
        args = ["route53", "list-resource-record-sets", "--hosted-zone-id", zone_id, "--output", "json"]
        payload = json.loads(_run(args))
        records.extend(payload.get("ResourceRecordSets", []))
        while payload.get("IsTruncated"):
            payload = json.loads(
                _run(
                    args
                    + [
                        "--start-record-name",
                        payload["NextRecordName"],
                        "--start-record-type",
                        payload["NextRecordType"],
                    ]
                )
            )
            records.extend(payload.get("ResourceRecordSets", []))
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
        return {"zone_id": zone_id, "records": summaries}

    def upsert(self, name: str, address: str, record_type: str = "A", ttl: int = 300) -> dict:
        zone_id = self._zone_id(None)
        fqdn = name if name.endswith(f".{self.cfg.dns_zone}") else f"{name}.{self.cfg.dns_zone}"
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
        out = _run(
            [
                "route53",
                "change-resource-record-sets",
                "--hosted-zone-id",
                zone_id,
                "--change-batch",
                json.dumps(change),
                "--output",
                "json",
            ]
        )
        entry = record("networking.dns_upsert", fqdn, "ok", {"address": address, "type": record_type})
        return {"result": "ok", "fqdn": fqdn, "address": address, "output": out, "event": entry}

    def resolve(self, name: str) -> dict:
        out = runners.run(["dig", "+short", name], timeout=15)
        return {"name": name, "resolved": out.split()}
