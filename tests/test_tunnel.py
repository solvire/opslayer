"""Tests for the tunnel provider registry + frp route verbs (mirrors test_networking)."""

import pytest

from opslayer.config import Config
from opslayer.operations import networking
from opslayer.operations.tunnel import available_providers, get_provider
from opslayer.operations.tunnel.frp import FrpProvider, _split_target, _toml

CFG = Config(frp_server="44.242.82.136", frp_token="tok", frp_port=7000)


def test_registry_has_frp():
    assert "frp" in available_providers()


def test_provider_dispatch():
    assert isinstance(get_provider("frp", CFG), FrpProvider)


def test_split_target_fqdn():
    assert _split_target("traefik.kube-system.svc.cluster.local") == (
        "traefik.kube-system.svc.cluster.local", 80)


def test_split_target_host_port():
    assert _split_target("192.168.0.100:80") == ("192.168.0.100", 80)


def test_split_target_url():
    assert _split_target("http://10.43.48.148:8080") == ("10.43.48.148", 8080)


def test_split_target_default_backend():
    assert _split_target("") == ("traefik.kube-system.svc.cluster.local", 80)


def test_toml_has_env_token_not_secret():
    toml = _toml(CFG, ["example.com", "www.example.com"], "traefik.kube-system.svc.cluster.local")
    assert "{{ .Envs.FRP_TOKEN }}" in toml
    assert '"tok"' not in toml  # the raw token must never be rendered into config
    assert "serverAddr = \"44.242.82.136\"" in toml
    assert "customDomains = [\"example.com\", \"www.example.com\"]" in toml
    assert "serverPort = 7000" in toml
    assert "hostHeaderRewrite" not in toml  # absent when not requested


def test_toml_rewrite_host():
    toml = _toml(CFG, ["example.com"], "traefik.kube-system.svc.cluster.local",
                 rewrite_host="scotttactical.dtac.io")
    assert "hostHeaderRewrite = \"scotttactical.dtac.io\"" in toml


class StubKubectl:
    """Records kubectl calls; returns canned outputs for get."""

    def __init__(self):
        self.calls = []
        self.cm_json = '{"data": {"frpc.toml": "serverAddr = \\"x\\""}}'

    def __call__(self, args, *, timeout=60, input=None):
        self.calls.append((args, input))
        if "get" in args and "cm" in args:
            return self.cm_json
        if "get" in args and "deploy" in args:
            return "frpc   1/1    Running"
        return ""


@pytest.fixture()
def kubectl(monkeypatch):
    stub = StubKubectl()
    import opslayer.runners as runners

    monkeypatch.setattr(runners, "kubectl", stub)
    return stub


def test_facade_upsert_route(kubectl, monkeypatch):
    monkeypatch.setattr(networking, "get_tunnel_provider", lambda cfg=None: FrpProvider(CFG))
    result = networking.tunnel_upsert("scotttactical.com", "traefik.kube-system.svc.cluster.local", None, cfg=CFG)
    assert result["result"] == "ok"
    assert result["backend"] == "traefik.kube-system.svc.cluster.local"
    # one combined apply feeding stdin
    assert any("apply" in a for a, _ in kubectl.calls)


def test_facade_upsert_with_domains(kubectl, monkeypatch):
    monkeypatch.setattr(networking, "get_tunnel_provider", lambda cfg=None: FrpProvider(CFG))
    result = networking.tunnel_upsert(
        "scotttactical.com", "traefik.kube-system.svc.cluster.local",
        ["scotttactical.com", "www.scotttactical.com"], cfg=CFG,
    )
    assert result["domains"] == ["scotttactical.com", "www.scotttactical.com"]


def test_facade_delete_route(kubectl, monkeypatch):
    monkeypatch.setattr(networking, "get_tunnel_provider", lambda cfg=None: FrpProvider(CFG))
    result = networking.tunnel_delete("scotttactical.com", cfg=CFG)
    assert result["result"] == "ok"


def test_facade_status(kubectl, monkeypatch):
    monkeypatch.setattr(networking, "get_tunnel_provider", lambda cfg=None: FrpProvider(CFG))
    result = networking.tunnel_status(cfg=CFG)
    assert result["provider"] == "frp"
    assert "Running" in result["deployment"]


def test_missing_server_raises():
    with pytest.raises(LookupError):
        FrpProvider(Config(frp_server="", frp_token="")).upsert_route(
            "example.com", "traefik.kube-system.svc.cluster.local",
            domains=None,
            cfg=Config(frp_server="", frp_token=""),
        )


def test_multi_route_upsert_preserves_existing(monkeypatch):
    """Adding a new route must NOT drop an existing route in the live config."""
    existing = (
        'serverAddr = "44.242.82.136"\n'
        'serverPort = 7000\n'
        'auth.method = "token"\n'
        'auth.token = "{{ .Envs.FRP_TOKEN }}"\n\n'
        "[[proxies]]\n"
        'name = "theduber.club"\n'
        'type = "http"\n'
        'localIP = "traefik.kube-system.svc.cluster.local"\n'
        "localPort = 80\n"
        'customDomains = ["theduber.club", "www.theduber.club"]\n'
        'hostHeaderRewrite = "theduber.dtac.io"\n'
        "transport.useEncryption = true\n"
    )
    applied = {}

    class StubKubectl:
        def __init__(self):
            self.calls = []

        def __call__(self, args, *, timeout=60, input=None):
            self.calls.append((args, input))
            if "get" in args and "cm" in args:
                import json
                return json.dumps({"data": {"frpc.toml": existing}})
            if "apply" in args and input is not None:
                applied["combined"] = input
            if "get" in args and "deploy" in args:
                return "frpc   1/1    Running"
            return ""

    import opslayer.runners as runners
    monkeypatch.setattr(runners, "kubectl", StubKubectl())

    result = FrpProvider(CFG).upsert_route(
        "scotttactical.com",
        "traefik.kube-system.svc.cluster.local",
        domains=["scotttactical.com", "www.scotttactical.com"],
        cfg=CFG,
        rewrite_host="scotttactical.dtac.io",
    )
    assert result["result"] == "ok"
    assert result["routes"] == ["scotttactical.com", "theduber.club"]
    # the applied config must contain BOTH proxies
    combined = applied["combined"]
    assert "theduber.club" in combined
    assert "scotttactical.com" in combined
    # and both hostHeaderRewrite values survive
    assert "theduber.dtac.io" in combined
    assert "scotttactical.dtac.io" in combined


def test_multi_route_replaces_same_name(monkeypatch):
    """Re-upserting the SAME route replaces it, not duplicates it."""
    existing = (
        'serverAddr = "44.242.82.136"\n'
        'serverPort = 7000\n'
        'auth.method = "token"\n'
        'auth.token = "{{ .Envs.FRP_TOKEN }}"\n\n'
        "[[proxies]]\n"
        'name = "scotttactical.com"\n'
        'type = "http"\n'
        'localIP = "traefik.kube-system.svc.cluster.local"\n'
        "localPort = 80\n"
        'customDomains = ["scotttactical.com"]\n'
        "transport.useEncryption = true\n"
    )
    applied = {}

    class StubKubectl:
        def __call__(self, args, *, timeout=60, input=None):
            if "get" in args and "cm" in args:
                import json
                return json.dumps({"data": {"frpc.toml": existing}})
            if "apply" in args and input is not None:
                applied["combined"] = input
            if "get" in args and "deploy" in args:
                return "frpc   1/1    Running"
            return ""

    import opslayer.runners as runners
    monkeypatch.setattr(runners, "kubectl", StubKubectl())

    result = FrpProvider(CFG).upsert_route(
        "scotttactical.com",
        "traefik.kube-system.svc.cluster.local",
        domains=["scotttactical.com"],
        cfg=CFG,
    )
    assert result["result"] == "ok"
    assert result["routes"] == ["scotttactical.com"]
    assert applied["combined"].count("[[proxies]]") == 1