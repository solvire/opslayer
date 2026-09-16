import json
from pathlib import Path

import pytest

from opslayer.config import Config
from opslayer.operations import networking
from opslayer.operations.dns import get_provider

CFG = Config(dns_zone="example.com")

FIXTURE_ZONES = {
    "HostedZones": [
        {"Id": "/hostedzone/ZEXAMPLE123", "Name": "example.com.", "ResourceRecordSetCount": 12}
    ]
}

FIXTURE_RECORDS = {
    "ResourceRecordSets": [
        {
            "Name": "ops01.example.com.",
            "Type": "A",
            "TTL": 300,
            "ResourceRecords": [{"Value": "10.0.0.5"}],
        },
        {
            "Name": "example.com.",
            "Type": "NS",
            "TTL": 172800,
            "ResourceRecords": [{"Value": "ns-1.awsdns-01.com"}],
        },
        {
            "Name": "app.example.com.",
            "Type": "A",
            "AliasTarget": {"DNSName": "dualstack.elb.amazonaws.com"},
        },
    ],
    "IsTruncated": False,
}


class StubProvider:
    """Records runner calls; reuses Route53's command building via the same runner seam."""

    def __init__(self, calls):
        self.calls = calls

    def list_zones(self):
        self.calls.append(["aws", "route53", "list-hosted-zones"])
        return {"zones": [{"id": "ZEXAMPLE123", "name": "example.com", "records": 12}]}

    def list_records(self, zone):
        self.calls.append(["aws", "route53", "list-resource-record-sets", zone])
        return {"zone_id": "ZEXAMPLE123", "records": networking_summary()}

    def upsert(self, name, address, record_type="A", ttl=300):
        self.calls.append(["aws", "route53", "change-resource-record-sets", name, address])
        return {"result": "ok", "fqdn": name, "address": address}

    def resolve(self, name):
        return {"name": name, "resolved": []}


def networking_summary():
    return [
        {"name": "ops01.example.com", "type": "A", "ttl": 300, "values": [{"Value": "10.0.0.5"}], "alias": False},
        {"name": "app.example.com", "type": "A", "ttl": None, "values": [], "alias": True},
        {"name": "example.com", "type": "NS", "ttl": 172800, "values": [{"Value": "ns-1.awsdns-01.com"}], "alias": False},
    ]


@pytest.fixture()
def fake_aws(monkeypatch):
    calls = []
    stub = StubProvider(calls)
    monkeypatch.setattr(networking, "get_provider", lambda cfg=None: stub)
    return calls


def test_list_zones(fake_aws):
    result = networking.list_zones()
    assert result["zones"] == [{"id": "ZEXAMPLE123", "name": "example.com", "records": 12}]


def test_dns_list_parses_records(fake_aws):
    result = networking.dns_list("ZEXAMPLE123")
    names = {r["name"]: r for r in result["records"]}
    assert names["ops01.example.com"]["values"] == [{"Value": "10.0.0.5"}]
    assert names["app.example.com"]["alias"] is True
    assert names["example.com"]["type"] == "NS"
    assert json.dumps(result)  # json-able contract


def test_dns_upsert_dispatches_to_provider(fake_aws):
    result = networking.dns_upsert("ops01", "10.0.0.6", ttl=300, cfg=CFG)
    assert result["result"] == "ok"
    assert ["aws", "route53", "change-resource-record-sets", "ops01", "10.0.0.6"] in fake_aws


def test_zone_discovery_by_name(fake_aws):
    result = networking.dns_list(None, cfg=CFG)
    assert result["zone_id"] == "ZEXAMPLE123"


def test_registry_dispatches_by_name():
    from opslayer.operations.dns import available_providers
    assert "route53" in available_providers()
