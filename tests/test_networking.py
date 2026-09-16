import json
from pathlib import Path

import pytest

from opslayer.config import Config
from opslayer.operations import networking

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


@pytest.fixture()
def fake_aws(monkeypatch):
    calls = []

    def fake_run(cmd, timeout=60):
        calls.append(cmd)
        if "list-hosted-zones" in cmd:
            return json.dumps(FIXTURE_ZONES)
        if "list-resource-record-sets" in cmd:
            return json.dumps(FIXTURE_RECORDS)
        if "change-resource-record-sets" in cmd:
            return json.dumps({"ChangeInfo": {"Id": "/change/C1", "Status": "PENDING"}})
        raise AssertionError(f"unexpected aws call: {cmd}")

    monkeypatch.setattr(networking.runners, "run", fake_run)
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


def test_dns_upsert_builds_change_batch(fake_aws):
    result = networking.dns_upsert("ops01", "10.0.0.6", ttl=300, cfg=CFG)
    change_cmd = next(c for c in fake_aws if "change-resource-record-sets" in c)
    batch = json.loads(change_cmd[change_cmd.index("--change-batch") + 1])
    rrset = batch["Changes"][0]["ResourceRecordSet"]
    assert rrset["Name"] == "ops01.example.com"
    assert rrset["ResourceRecords"] == [{"Value": "10.0.0.6"}]
    assert result["result"] == "ok"


def test_upsert_fqdn_passthrough(fake_aws):
    networking.dns_upsert("ops01.example.com", "10.0.0.6", cfg=CFG)
    change_cmd = next(c for c in fake_aws if "change-resource-record-sets" in c)
    batch = json.loads(change_cmd[change_cmd.index("--change-batch") + 1])
    assert batch["Changes"][0]["ResourceRecordSet"]["Name"] == "ops01.example.com"


def test_zone_discovery_by_name(fake_aws):
    result = networking.dns_list(None, cfg=CFG)
    assert result["zone_id"] == "ZEXAMPLE123"
