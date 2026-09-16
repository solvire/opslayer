"""AWS Route53 provider. Talks boto3 directly - no AWS CLI subprocess.

Credentials: boto3's standard chain applies. The supported path for opslayer
is the repo-root .env carrying the standard AWS_* variables (gitignored, see
.env.example); explicit session/CLI profiles also work untouched.

Least-privilege policy for the key (Route53 only, one zone):
  route53:ListHostedZones, route53:GetChange          -> Resource: *
  route53:ListResourceRecordSets,
  route53:ChangeResourceRecordSets                    -> Resource: the zone ARN
"""

from __future__ import annotations

import ipaddress

import boto3

from opslayer.config import Config
from opslayer.events import record
from . import register


def infer_record_type(value: str) -> str:
    """A for IPv4, AAAA for IPv6, CNAME for anything else."""
    try:
        ipaddress.IPv4Address(value)
        return "A"
    except ValueError:
        pass
    try:
        ipaddress.IPv6Address(value)
        return "AAAA"
    except ValueError:
        return "CNAME"


def _paginate(client, method: str, key: str, **kwargs) -> list[dict]:
    paginator = client.get_paginator(method)
    items: list[dict] = []
    for page in paginator.paginate(**kwargs):
        items.extend(page.get(key, []))
    return items


@register("route53")
class Route53Provider:
    def __init__(self, cfg: Config | None = None, client=None):
        self.cfg = cfg or Config.load()
        self._client = client

    @property
    def client(self):
        if self._client is None:
            self._client = boto3.client("route53")
        return self._client

    def list_zones(self) -> dict:
        zones = _paginate(self.client, "list_hosted_zones", "HostedZones")
        return {
            "zones": [
                {
                    "id": z["Id"].split("/")[-1],
                    "name": z["Name"].rstrip("."),
                    "records": z["ResourceRecordSetCount"],
                }
                for z in zones
            ]
        }

    def _zone_id(self, zone: str | None) -> str:
        if zone:
            return zone
        name = self.cfg.dns_zone
        matches = [z for z in self.list_zones()["zones"] if z["name"] == name]
        if not matches:
            raise LookupError(f"no hosted zone found for {name}")
        return matches[0]["id"]

    @staticmethod
    def _summary(r: dict) -> dict:
        return {
            "name": r["Name"].rstrip("."),
            "type": r["Type"],
            "ttl": r.get("TTL"),
            "values": r.get("ResourceRecords", []),
            "alias": "AliasTarget" in r,
        }

    def list_records(self, zone: str | None = None) -> dict:
        zone_id = self._zone_id(zone)
        raw = _paginate(self.client, "list_resource_record_sets", "ResourceRecordSets", HostedZoneId=zone_id)
        return {"zone_id": zone_id, "records": [self._summary(r) for r in raw]}

    def upsert(self, name: str, address: str, record_type: str | None = None, ttl: int = 300) -> dict:
        zone_id = self._zone_id(None)
        fqdn = name if name.endswith(f".{self.cfg.dns_zone}") else f"{name}.{self.cfg.dns_zone}"
        resolved_type = record_type or infer_record_type(address)
        response = self.client.change_resource_record_sets(
            HostedZoneId=zone_id,
            ChangeBatch={
                "Comment": f"opslayer upsert {fqdn}",
                "Changes": [
                    {
                        "Action": "UPSERT",
                        "ResourceRecordSet": {
                            "Name": fqdn,
                            "Type": resolved_type,
                            "TTL": ttl,
                            "ResourceRecords": [{"Value": address}],
                        },
                    }
                ],
            },
        )
        entry = record(
            "networking.dns_upsert", fqdn, "ok",
            {"address": address, "type": resolved_type},
        )
        return {
            "result": "ok",
            "fqdn": fqdn,
            "address": address,
            "record_type": resolved_type,
            "change_id": response["ChangeInfo"]["Id"],
            "status": response["ChangeInfo"]["Status"],
            "event": entry,
        }

    def delete(self, name: str, record_type: str = "A", *, all_values: bool = False) -> dict:
        """Delete a record. Non-alias records must match their stored values exactly,
        so this reads the record first and replays it with Action=DELETE."""
        zone_id = self._zone_id(None)
        fqdn = name if name.endswith(f".{self.cfg.dns_zone}") else f"{name}.{self.cfg.dns_zone}"
        existing = [
            r
            for r in self.client.list_resource_record_sets(HostedZoneId=zone_id).get("ResourceRecordSets", [])
            if r["Name"].rstrip(".") == fqdn and r["Type"] == record_type and "AliasTarget" not in r
        ]
        if not existing:
            raise LookupError(f"no deletable {record_type} record named {fqdn}")
        target = existing[0] if all_values or len(existing) == 1 else existing[0]
        response = self.client.change_resource_record_sets(
            HostedZoneId=zone_id,
            ChangeBatch={
                "Comment": f"opslayer delete {fqdn}",
                "Changes": [{"Action": "DELETE", "ResourceRecordSet": target}],
            },
        )
        entry = record("networking.dns_delete", fqdn, "ok", {"type": record_type})
        return {"result": "ok", "fqdn": fqdn, "change_id": response["ChangeInfo"]["Id"], "event": entry}

    def resolve(self, name: str) -> dict:
        from ... import runners

        out = runners.run(["dig", "+short", name], timeout=15)
        return {"name": name, "resolved": out.split()}
