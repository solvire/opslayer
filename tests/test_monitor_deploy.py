"""Monitor deploy + status tests.

The monitoring stack templates ship in a PUBLIC repo, so a hard gate here
asserts no template embeds a private IP or hostname. Deploy/status are tested
with the ssh/remote_write runners monkeypatched (no real SSH in tests).
"""

import re
from pathlib import Path

from opslayer.config import Config
from opslayer.operations import monitoring

TEMPLATES = Path(__file__).resolve().parents[1] / "src" / "opslayer" / "templates"
_PRIVATE_IP = re.compile(r"\b(?:192\.168\.|10\.|172\.(?:1[6-9]|2\d|3[01])\.)\d+\.\d+\b")

ALL_TEMPLATE_FILES = [
    p for p in TEMPLATES.rglob("*") if p.is_file()
]


def _cfg(**overrides) -> Config:
    base = {
        "ops_host": "ops.example.com",
        "monitor_ssh_user": "solvire",
        "gatus_port": 8080,
        "nut_exporter_port": 9199,
        "nut_server": "nut.example.com",
        "nut_ups_name": "rackups",
        "argocd_url": "https://argocd.example.com",
        "argocd_api_key": "dummy-key-for-test",
        "monitor_endpoints": "https://site-a.example.com, https://site-b.example.com",
        "beszel_key": "dummy-beszel-key",
        "beszel_token": "dummy-beszel-token",
        "beszel_hub_url": "http://127.0.0.1:8090",
    }
    base.update(overrides)
    return Config(**base)


def _good_status(command: str) -> tuple[int, str]:
    """Remote output for a healthy Debian aarch64 box."""
    if "uname" in command:
        return 0, "aarch64"
    if "os-release" in command:
        return 0, "ID=raspbian\nID_LIKE=debian"
    if "command -v apt-get" in command:
        return 0, "yes"
    if "sudo -n" in command:
        return 0, "yes"
    if "free -m" in command:
        return 0, "Mem: 1844 174 1445 12 299 1669"
    if "df -m" in command:
        return 0, "/dev/root 117000 4100 109000 4% /"
    if "echo ready" in command:
        return 0, "ready"
    return 0, "yes"


def test_templates_have_no_hardcoded_private_ips():
    assert ALL_TEMPLATE_FILES, "expected template files to exist"
    for path in ALL_TEMPLATE_FILES:
        text = path.read_text(encoding="utf-8")
        hits = _PRIVATE_IP.findall(text)
        assert not hits, f"{path.relative_to(TEMPLATES)} contains private IP(s): {hits}"


def test_templates_use_only_known_placeholders():
    known = {
        "OPSLAYER_OPS_HOST", "OPSLAYER_GATUS_PORT", "OPSLAYER_NUT_EXPORTER_PORT",
        "OPSLAYER_ARGOCD_URL", "OPSLAYER_ARGOCD_API_KEY", "OPSLAYER_MONITOR_ENDPOINTS",
        "OPSLAYER_MONITOR_SSH_USER", "OPSLAYER_NUT_SERVER", "OPSLAYER_NUT_UPS_NAME",
        "OPSLAYER_BESZEL_ADMIN_USER", "OPSLAYER_BESZEL_ADMIN_PASSWORD",
        "OPSLAYER_BESZEL_KEY", "OPSLAYER_BESZEL_TOKEN", "OPSLAYER_BESZEL_HUB_URL",
    }
    placeholder = re.compile(r"\$\{?([A-Z][A-Z0-9_]*)\}?")
    for path in ALL_TEMPLATE_FILES:
        for name in placeholder.findall(path.read_text(encoding="utf-8")):
            assert name in known, f"{path.name}: unknown placeholder ${name}"


def test_render_substitutes_env():
    rendered = monitoring._render(
        "port: ${OPSLAYER_GATUS_PORT}\nhost: ${OPSLAYER_OPS_HOST}\n",
        {"OPSLAYER_GATUS_PORT": "8080", "OPSLAYER_OPS_HOST": "ops.example.com"},
    )
    assert rendered == "port: 8080\nhost: ops.example.com\n"


def test_deploy_gatus_calls_runners(monkeypatch):
    calls: dict[str, list] = {"ssh": [], "write": [], "sysctl": []}

    def fake_ssh(user, host, command, **kw):
        calls["ssh"].append((user, host, command))
        return "no" if command.startswith("id ") else ""

    def fake_write(user, host, remote_path, content, **kw):
        calls["write"].append((user, host, remote_path, content))
        return ""

    def fake_sysctl(user, host, action, unit, **kw):
        calls["sysctl"].append((user, host, action, unit))
        return ""

    monkeypatch.setattr(monitoring.runners, "ssh", fake_ssh)
    monkeypatch.setattr(monitoring.runners, "remote_write", fake_write)
    monkeypatch.setattr(monitoring.runners, "remote_systemctl", fake_sysctl)

    result = monitoring.deploy("gatus", cfg=_cfg())

    assert result["result"] == "ok"
    assert result["stack"] == "gatus"
    assert set(result["deployed"]) == {"gatus", "nut_exporter"}

    # service users created (id returns "no", so useradd issued)
    useradds = [c[2] for c in calls["ssh"] if "useradd" in c[2]]
    assert any("gatus" in u for u in useradds)
    assert any("nut" in u for u in useradds)

    written = {c[2] for c in calls["write"]}
    assert "/opt/gatus/config.yaml" in written
    assert "/etc/systemd/system/gatus.service" in written
    assert "/etc/systemd/system/nut-exporter.service" in written

    # endpoints marker expanded to one entry per monitor_endpoints URL
    config = next(c[3] for c in calls["write"] if c[2].endswith("config.yaml"))
    assert "https://site-a.example.com" in config
    assert "https://site-b.example.com" in config
    assert "[[ENDPOINTS]]" not in config

    # secret values flow through to the remote file (never printed)
    assert "dummy-key-for-test" in config

    # units enabled with --now
    enables = [(c[2], c[3]) for c in calls["sysctl"] if c[2] == "enable"]
    assert ("enable", "nut-exporter --now") in enables
    assert ("enable", "gatus --now") in enables


def test_deploy_beszel(monkeypatch):
    calls: dict[str, list] = {"write": [], "sysctl": [], "ssh": []}

    def fake_write(user, host, remote_path, content, **kw):
        calls["write"].append((user, host, remote_path, content))
        return ""

    def fake_ssh(user, host, command, **kw):
        calls["ssh"].append((user, host, command))
        return "no" if command.startswith("id ") else ""

    def fake_sysctl(user, host, action, unit, **kw):
        calls["sysctl"].append((user, host, action, unit))
        return ""

    monkeypatch.setattr(monitoring.runners, "ssh", fake_ssh)
    monkeypatch.setattr(monitoring.runners, "remote_write", fake_write)
    monkeypatch.setattr(monitoring.runners, "remote_systemctl", fake_sysctl)

    result = monitoring.deploy("beszel", cfg=_cfg())

    assert set(result["deployed"]) == {"beszel-hub", "beszel-agent"}
    written = {c[2] for c in calls["write"]}
    assert "/opt/beszel/agent/agent.env" in written
    assert "/etc/systemd/system/beszel-hub.service" in written
    assert any("beszel" in c[2] for c in calls["ssh"] if "useradd" in c[2])
    # credentials render from .env so a re-deploy is idempotent (no clobber)
    agent_env = next(c[3] for c in calls["write"] if c[2].endswith("agent.env"))
    assert "KEY=dummy-beszel-key" in agent_env
    assert "TOKEN=dummy-beszel-token" in agent_env
    assert "HUB_URL=http://127.0.0.1:8090" in agent_env
    # working dir chowned to the service user
    assert any("chown -R beszel:beszel" in c[2] for c in calls["ssh"])


def test_deploy_unknown_stack_raises():
    import pytest

    with pytest.raises(Exception):
        monitoring.deploy("bogus", cfg=_cfg())


def _wire_beszel_mocks(monkeypatch):
    calls = {"write": [], "sysctl": [], "ssh": []}

    def fake_write(user, host, path, content, **kw):
        calls["write"].append((path, content))
        return ""

    def fake_ssh(user, host, command, **kw):
        calls["ssh"].append(command)
        return ""

    def fake_sysctl(user, host, action, unit, **kw):
        calls["sysctl"].append((action, unit))
        return ""

    def fake_status(user, host, command, **kw):
        if "ssh-keygen" in command:
            return 0, "ssh-ed25519 AAAAC3Nz test@hub"
        return 0, ""

    monkeypatch.setattr(monitoring.runners, "remote_write", fake_write)
    monkeypatch.setattr(monitoring.runners, "ssh", fake_ssh)
    monkeypatch.setattr(monitoring.runners, "remote_systemctl", fake_sysctl)
    monkeypatch.setattr(monitoring.runners, "remote_status", fake_status)
    return calls


def test_beszel_sync_reuses_existing_universal_token(monkeypatch):
    calls = _wire_beszel_mocks(monkeypatch)

    def fake_http(url, *, method="GET", body=None, token=None, timeout=15):
        if url.endswith("/api/beszel/first-run"):
            return {"firstRun": False}
        if "auth-with-password" in url:
            return {"token": "usertok"}
        if "universal-token" in url:
            # a read (no enable=) returns the existing permanent token
            return {"token": "univtok", "active": True, "permanent": True}
        return {}

    monkeypatch.setattr(monitoring, "_http_json", fake_http)

    cfg = _cfg(beszel_key="", beszel_token="", beszel_admin_email="admin@example.com", beszel_admin_password="pw")
    result = monitoring.beszel_sync(cfg=cfg)

    assert result["token_source"] == "universal-existing"
    agent_env = next(c for p, c in calls["write"] if p == "/opt/beszel/agent/agent.env")
    assert "KEY=ssh-ed25519 AAAAC3Nz test@hub" in agent_env
    assert "TOKEN=univtok" in agent_env
    assert ("restart", "beszel-agent") in calls["sysctl"]


def test_beszel_sync_creates_token_when_none_exists(monkeypatch):
    _wire_beszel_mocks(monkeypatch)

    def fake_http(url, *, method="GET", body=None, token=None, timeout=15):
        if url.endswith("/api/beszel/first-run"):
            return {"firstRun": False}
        if "auth-with-password" in url:
            return {"token": "usertok"}
        if "universal-token" in url:
            # the plain read has no permanent token; only enable=1 creates one
            if "enable=1" in url:
                return {"token": "newtok", "active": True, "permanent": True}
            return {"token": "", "active": False, "permanent": False}
        return {}

    monkeypatch.setattr(monitoring, "_http_json", fake_http)

    cfg = _cfg(beszel_key="", beszel_token="", beszel_admin_email="a@b.c", beszel_admin_password="pw")
    result = monitoring.beszel_sync(cfg=cfg)

    assert result["token_source"] == "universal-new"


def test_beszel_sync_creates_first_user(monkeypatch):
    _wire_beszel_mocks(monkeypatch)
    posted = []

    def fake_http(url, *, method="GET", body=None, token=None, timeout=15):
        if url.endswith("/api/beszel/first-run"):
            return {"firstRun": True}
        if url.endswith("/api/beszel/create-user"):
            posted.append(body)
            return {"msg": "User created"}
        if "auth-with-password" in url:
            return {"token": "usertok"}
        if "universal-token" in url:
            return {"token": "univtok", "permanent": True}
        return {}

    monkeypatch.setattr(monitoring, "_http_json", fake_http)

    cfg = _cfg(beszel_key="", beszel_token="", beszel_admin_email="a@b.c", beszel_admin_password="pw")
    monitoring.beszel_sync(cfg=cfg)

    assert posted and posted[0]["email"] == "a@b.c"


def test_stack_status_maps_active(monkeypatch):
    def fake_remote_status(user, host, command, **kw):
        unit = command.split()[-1]
        return (0, "active") if unit == "gatus.service" else (3, "inactive")

    monkeypatch.setattr(monitoring.runners, "remote_status", fake_remote_status)

    result = monitoring.stack_status(cfg=_cfg())
    assert result["host"] == "ops.example.com"
    assert result["services"]["gatus"] == "active"
    assert result["services"]["nut_exporter"] == "inactive"


def test_stack_status_missing_service(monkeypatch):
    def fake_remote_status(user, host, command, **kw):
        return 3, "inactive"

    monkeypatch.setattr(monitoring.runners, "remote_status", fake_remote_status)

    result = monitoring.stack_status(cfg=_cfg())
    assert result["services"]["gatus"] == "inactive"


# --- probe ----------------------------------------------------------------


def _good_probe(monkeypatch):
    """Install a remote_status fake that returns a healthy Debian aarch64 box."""
    def fake_remote_status(user, host, command, **kw):
        return _good_status(command)

    monkeypatch.setattr(monitoring.runners, "remote_status", fake_remote_status)


def test_probe_ok(monkeypatch):
    _good_probe(monkeypatch)
    result = monitoring.probe(cfg=_cfg())
    assert result["ok"] is True
    assert result["checks"]["arch"]["ok"] is True
    assert result["checks"]["os"]["ok"] is True


def test_probe_fails_closed_on_wrong_arch(monkeypatch):
    def fake_remote_status(user, host, command, **kw):
        if "uname" in command:
            return 0, "x86_64"
        if "os-release" in command:
            return 0, "ID=ubuntu"
        if "sudo -n" in command:
            return 0, "yes"
        if "echo ready" in command:
            return 0, "ready"
        return 0, "yes"

    monkeypatch.setattr(monitoring.runners, "remote_status", fake_remote_status)
    result = monitoring.probe(cfg=_cfg())
    assert result["ok"] is False
    assert result["checks"]["arch"]["ok"] is False


def test_probe_fails_closed_on_ssh_unreachable(monkeypatch):
    def fake_remote_status(user, host, command, **kw):
        if "echo ready" in command:
            return 1, ""
        return 0, "yes"

    monkeypatch.setattr(monitoring.runners, "remote_status", fake_remote_status)
    result = monitoring.probe(cfg=_cfg())
    assert result["ok"] is False
    assert result["reason"] == "ssh-unreachable"


def test_probe_no_ops_host():
    result = monitoring.probe(cfg=_cfg(ops_host=""))
    assert result["ok"] is False


# --- bootstrap -------------------------------------------------------------


def test_bootstrap_probe_gates_install(monkeypatch):
    """Bootstrap must refuse to install when the probe fails."""
    def fake_remote_status(user, host, command, **kw):
        if "uname" in command:
            return 0, "x86_64"  # fails the probe
        if "os-release" in command:
            return 0, "ID=ubuntu"
        if "sudo -n" in command:
            return 0, "yes"
        if "echo ready" in command:
            return 0, "ready"
        return 0, "yes"

    monkeypatch.setattr(monitoring.runners, "remote_status", fake_remote_status)
    # any install that reaches ssh would raise if called
    monkeypatch.setattr(monitoring.runners, "ssh", lambda *a, **k: (_ for _ in ()).throw(AssertionError("ssh should not run on failed probe")))
    result = monitoring.bootstrap("all", cfg=_cfg())
    assert result["result"] == "blocked"


def test_bootstrap_skips_existing(monkeypatch):
    def fake_remote_status(user, host, command, **kw):
        if "test -x" in command:
            return 0, "yes"  # already installed -> skip
        return _good_status(command)

    monkeypatch.setattr(monitoring.runners, "remote_status", fake_remote_status)
    ssh_calls: list[str] = []
    monkeypatch.setattr(monitoring.runners, "ssh", lambda *a, command="", **k: ssh_calls.append(command) or "")

    result = monitoring.bootstrap("all", cfg=_cfg())
    assert result["result"] == "ok"
    assert set(result["skipped"]) == {"beszel", "beszel-agent", "nut_exporter", "gatus"}
    assert result["installed"] == []