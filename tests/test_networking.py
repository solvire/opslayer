import pytest

from opslayer.config import Config
from opslayer.operations import networking
from opslayer.operations.dns import available_providers, get_provider
from opslayer.operations.dns.route53 import Route53Provider

CFG = Config(dns_zone="example.com")


class StubRoute53Client:
    """Mirrors boto3 route53 shapes opslayer consumes."""

    def __init__(self):
        self.calls = []

    def get_paginator(self, method):
        if method == "list_hosted_zones":
            return _Paginator([{"HostedZones": [
                {"Id": "/hostedzone/ZEXAMPLE123", "Name": "example.com.", "ResourceRecordSetCount": 12},
            ]}])
        if method == "list_resource_record_sets":
            return _Paginator([{"ResourceRecordSets": [
                {"Name": "ops01.example.com.", "Type": "A", "TTL": 300,
                 "ResourceRecords": [{"Value": "10.0.0.5"}]},
                {"Name": "app.example.com.", "Type": "A",
                 "AliasTarget": {"DNSName": "dualstack.elb.amazonaws.com"}},
                {"Name": "example.com.", "Type": "NS", "TTL": 172800,
                 "ResourceRecords": [{"Value": "ns-1.awsdns-01.com"}]},
            ]}])
        raise AssertionError(f"unexpected paginator: {method}")

    def change_resource_record_sets(self, **kwargs):
        self.calls.append(("change", kwargs))
        return {"ChangeInfo": {"Id": "/change/C1", "Status": "PENDING"}}

    def list_resource_record_sets(self, **kwargs):
        self.calls.append(("list", kwargs))
        return {"ResourceRecordSets": [
            {"Name": "test.example.com.", "Type": "A", "TTL": 300,
             "ResourceRecords": [{"Value": "10.0.0.99"}]},
        ]}


class _Paginator:
    def __init__(self, pages):
        self.pages = pages

    def paginate(self, **kwargs):
        return iter(self.pages)


@pytest.fixture()
def client(monkeypatch):
    stub = StubRoute53Client()
    monkeypatch.setattr(Route53Provider, "client", property(lambda self: stub))
    return stub


def test_registry_has_route53():
    assert "route53" in available_providers()


def test_provider_dispatch(cfg=None):
    assert isinstance(get_provider("route53", CFG), Route53Provider)


def test_list_zones(client):
    result = Route53Provider(CFG).list_zones()
    assert result["zones"] == [{"id": "ZEXAMPLE123", "name": "example.com", "records": 12}]


def test_list_records(client):
    result = Route53Provider(CFG).list_records()
    names = {r["name"]: r for r in result["records"]}
    assert names["ops01.example.com"]["values"] == [{"Value": "10.0.0.5"}]
    assert names["app.example.com"]["alias"] is True
    assert names["example.com"]["type"] == "NS"
    assert result["zone_id"] == "ZEXAMPLE123"


def test_upsert(client):
    result = Route53Provider(CFG).upsert("ops01", "10.0.0.6", ttl=300)
    assert result["result"] == "ok"
    assert result["fqdn"] == "ops01.example.com"
    assert result["status"] == "PENDING"
    method, kwargs = client.calls[0]
    assert method == "change"
    rrset = kwargs["ChangeBatch"]["Changes"][0]["ResourceRecordSet"]
    assert rrset["Name"] == "ops01.example.com"
    assert rrset["ResourceRecords"] == [{"Value": "10.0.0.6"}]


def test_upsert_fqdn_passthrough(client):
    result = Route53Provider(CFG).upsert("ops01.example.com", "10.0.0.6")
    assert result["fqdn"] == "ops01.example.com"


def test_delete(client):
    result = Route53Provider(CFG).delete("test", "A")
    assert result["result"] == "ok"
    method, kwargs = next(c for c in client.calls if c[0] == "change")
    change = kwargs["ChangeBatch"]["Changes"][0]
    assert change["Action"] == "DELETE"
    assert change["ResourceRecordSet"]["Name"] == "test.example.com."


def test_delete_missing_raises(client):
    with pytest.raises(LookupError):
        Route53Provider(CFG).delete("nonexistent", "A")


def test_facade_dispatch(client, monkeypatch):
    monkeypatch.setattr(networking, "get_provider", lambda cfg=None: Route53Provider(CFG, client))
    result = networking.dns_upsert("ops01", "10.0.0.7", cfg=CFG)
    assert result["result"] == "ok"
    assert networking.dns_list()["zone_id"] == "ZEXAMPLE123"


def test_zone_discovery_by_name(client):
    assert Route53Provider(CFG).list_records()["zone_id"] == "ZEXAMPLE123"


def test_infer_record_type():
    from opslayer.operations.dns.route53 import infer_record_type

    assert infer_record_type("10.0.0.5") == "A"
    assert infer_record_type("fd00::1") == "AAAA"
    assert infer_record_type("nas.dtac.io") == "CNAME"


def test_upsert_infers_type_from_value(client):
    result = Route53Provider(CFG).upsert("ops01", "10.0.0.5")
    assert result["record_type"] == "A"
    result = Route53Provider(CFG).upsert("nas-alias", "nas.dtac.io")
    assert result["record_type"] == "CNAME"
