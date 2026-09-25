"""Monitoring: status of nodes, apps, and services; alert surface; stack deploy.

The monitoring stack (Gatus dashboard + nut_exporter UPS feed + Beszel host
metrics) is deployed onto the ops controller via `deploy`. Config templates live
in this package (src/opslayer/templates/) and are parameterized by the operator's
.env values - the repo stays public, so no IPs, hostnames, or secrets appear here.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

from ..config import Config
from ..events import record
from .. import runners

_TEMPLATES = Path(__file__).resolve().parents[1] / "templates"
_ENV_RE = re.compile(r"\$\{?([A-Z0-9_]+)\}?")

# Beszel hub internals (stable on-disk / HTTP surface we rely on):
# - the hub writes its ED25519 keypair to <dataDir>/id_ed25519 (GetSSHKey)
# - the hub data dir is beszel_data/ under its WorkingDirectory
# - first user: POST /api/beszel/create-user {"email","password"} (only while none)
# - auth:       POST /api/collections/users/auth-with-password
# - token:      GET  /api/beszel/universal-token?enable=1&permanent=1 (auth)
# - key:        GET  /api/beszel/info (auth) or ssh-keygen over SSH
_BESZEL_HUB_KEY_PATH = "/opt/beszel/hub/beszel_data/id_ed25519"

# bootstrap target binaries installed to /usr/local/bin
_BINARIES = {
    "gatus": "/usr/local/bin/gatus",
    "beszel": "/usr/local/bin/beszel",
    "beszel-agent": "/usr/local/bin/beszel-agent",
    "nut_exporter": "/usr/local/bin/nut_exporter",
}
_GATUS_REF = "github.com/TwiN/gatus/v5@latest"
_GO_TARBALL = "https://go.dev/dl/go1.22.0.linux-arm64.tar.gz"

# service name -> systemd unit basename
_STACK = {
    "gatus": "gatus.service",
    "nut_exporter": "nut-exporter.service",
    "beszel": "beszel-hub.service",
    "beszel-agent": "beszel-agent.service",
}


def nodes(*, cfg: Config | None = None) -> dict:
    cfg = cfg or Config.load()
    out = runners.kubectl(["get", "nodes", "-o", "wide"])
    return {"nodes": out}


def pods(namespace: str | None = None, *, cfg: Config | None = None) -> dict:
    cfg = cfg or Config.load()
    args = ["get", "pods", "-A"] if namespace is None else ["get", "pods", "-n", namespace]
    args += ["-o", "wide"]
    out = runners.kubectl(args)
    return {"namespace": namespace or "all", "pods": out}


def summary(*, cfg: Config | None = None) -> dict:
    cfg = cfg or Config.load()
    return {
        "nodes": runners.kubectl(["get", "nodes", "--no-headers"]).count("\n") + 1,
        "gatus": f"http://{cfg.ops_host}:{cfg.gatus_port}",
        "beszel": f"http://{cfg.ops_host}:8090",
    }


def _render(template: str, env: dict[str, str]) -> str:
    """Substitute ${VAR} / $VAR placeholders in a template from an env mapping."""
    def _sub(match: re.Match) -> str:
        return env.get(match.group(1), "")

    return _ENV_RE.sub(_sub, template)


def _template_path(name: str) -> Path:
    path = _TEMPLATES / name
    if not path.exists():
        raise runners.OpError(f"monitor template not found: {path}")
    return path


def deploy(stack: str, *, cfg: Config | None = None) -> dict:
    """Deploy the monitoring stack onto the ops controller.

    stack: "gatus" (Gatus + nut_exporter), "beszel" (Beszel hub + agent), or "all".
    Templates are rendered with the operator's .env values and pushed over SSH.
    """
    cfg = cfg or Config.load()
    if not cfg.ops_host:
        raise runners.OpError("OPSLAYER_OPS_HOST is not set; monitor deploy targets the ops controller")
    if stack not in ("gatus", "beszel", "all"):
        raise runners.OpError(f"unknown stack {stack!r}; expected 'gatus', 'beszel', or 'all'")

    env = _env(cfg)

    deployed: list[str] = []
    if stack in ("gatus", "all"):
        deployed += _deploy_gatus(env, cfg)
    if stack in ("beszel", "all"):
        deployed += _deploy_beszel(env, cfg)
        # auto-wire credentials (create hub user if absent, mint universal token,
        # read the hub key) whenever an admin is configured - no browser step.
        if cfg.beszel_admin_email and cfg.beszel_admin_password:
            try:
                beszel_sync(cfg=cfg, env=env)
            except runners.OpError as exc:
                record("monitor.beszel_sync", cfg.ops_host, "error", {"detail": str(exc)})
                return {
                    "result": "partial",
                    "host": cfg.ops_host,
                    "stack": stack,
                    "deployed": deployed,
                    "beszel_sync": {"ok": False, "error": str(exc)},
                }

    record("monitor.deploy", cfg.ops_host, "ok", {"stack": stack, "services": deployed})
    return {"result": "ok", "host": cfg.ops_host, "stack": stack, "deployed": deployed}


def _env(cfg: Config) -> dict[str, str]:
    return {
        "OPSLAYER_OPS_HOST": cfg.ops_host,
        "OPSLAYER_GATUS_PORT": str(cfg.gatus_port),
        "OPSLAYER_NUT_EXPORTER_PORT": str(cfg.nut_exporter_port),
        "OPSLAYER_ARGOCD_URL": cfg.argocd_url,
        "OPSLAYER_ARGOCD_API_KEY": cfg.argocd_api_key,
        "OPSLAYER_MONITOR_ENDPOINTS": cfg.monitor_endpoints,
        "OPSLAYER_MONITOR_SSH_USER": cfg.monitor_ssh_user,
        "OPSLAYER_NUT_SERVER": cfg.nut_server,
        "OPSLAYER_NUT_UPS_NAME": cfg.nut_ups_name,
        "OPSLAYER_BESZEL_KEY": cfg.beszel_key,
        "OPSLAYER_BESZEL_TOKEN": cfg.beszel_token,
        "OPSLAYER_BESZEL_HUB_URL": cfg.beszel_hub_url,
        "OPSLAYER_BESZEL_ADMIN_EMAIL": cfg.beszel_admin_email,
        "OPSLAYER_BESZEL_ADMIN_PASSWORD": cfg.beszel_admin_password,
    }


def _endpoints_yaml(cfg: Config) -> str:
    """Render OPSLAYER_MONITOR_ENDPOINTS (comma-separated URLs) as Gatus YAML."""
    if not cfg.monitor_endpoints:
        return ""
    lines: list[str] = []
    for url in (u.strip() for u in cfg.monitor_endpoints.split(",")):
        if not url:
            continue
        lines.append(f"  - name: {url}")
        lines.append("    group: sites")
        lines.append(f'    url: "{url}"')
        lines.append("    interval: 60s")
        lines.append("    conditions:")
        lines.append('      - "[STATUS] < 400"')
    return "\n".join(lines)


def _ensure_user(user: str, env: dict[str, str]) -> None:
    """Create an unprivileged service user idempotently if it does not exist."""
    exists = runners.ssh(
        env["OPSLAYER_MONITOR_SSH_USER"], env["OPSLAYER_OPS_HOST"], f"id {user} >/dev/null 2>&1 && echo yes || echo no"
    )
    if exists.strip() != "yes":
        runners.ssh(
            env["OPSLAYER_MONITOR_SSH_USER"],
            env["OPSLAYER_OPS_HOST"],
            f"sudo useradd -r -s /usr/sbin/nologin {user}",
        )


def _deploy_gatus(env: dict[str, str], cfg: Config) -> list[str]:
    remote_dir = "/opt/gatus"
    _ensure_user("gatus", env)
    _ensure_user("nut", env)
    runners.ssh(env["OPSLAYER_MONITOR_SSH_USER"], env["OPSLAYER_OPS_HOST"], f"sudo mkdir -p {remote_dir}")
    files = {
        "gatus/config.yaml": f"{remote_dir}/config.yaml",
        "gatus/gatus.service": "/etc/systemd/system/gatus.service",
        "nut_exporter/nut-exporter.service": "/etc/systemd/system/nut-exporter.service",
        "nut_exporter/env": f"{remote_dir}/nut_exporter.env",
    }
    for tpl, dest in files.items():
        content = _template_path(tpl).read_text(encoding="utf-8")
        if "[[ENDPOINTS]]" in content:
            content = content.replace("[[ENDPOINTS]]", _endpoints_yaml(cfg))
        rendered = _render(content, env)
        runners.remote_write(env["OPSLAYER_MONITOR_SSH_USER"], env["OPSLAYER_OPS_HOST"], dest, rendered)
    # config.yaml holds the ArgoCD token: keep it gatus-owned and 0600. The
    # service user must own /opt/gatus to write sqlite storage there.
    runners.ssh(
        env["OPSLAYER_MONITOR_SSH_USER"],
        env["OPSLAYER_OPS_HOST"],
        f"sudo chown -R gatus:gatus {remote_dir} && sudo chmod 600 {remote_dir}/config.yaml",
    )
    runners.remote_systemctl(env["OPSLAYER_MONITOR_SSH_USER"], env["OPSLAYER_OPS_HOST"], "daemon-reload", "")
    runners.remote_systemctl(env["OPSLAYER_MONITOR_SSH_USER"], env["OPSLAYER_OPS_HOST"], "enable", "nut-exporter --now")
    runners.remote_systemctl(env["OPSLAYER_MONITOR_SSH_USER"], env["OPSLAYER_OPS_HOST"], "enable", "gatus --now")
    return ["gatus", "nut_exporter"]


def _deploy_beszel(env: dict[str, str], cfg: Config) -> list[str]:
    remote_dir = "/opt/beszel"
    _ensure_user("beszel", env)
    runners.ssh(env["OPSLAYER_MONITOR_SSH_USER"], env["OPSLAYER_OPS_HOST"], f"sudo mkdir -p {remote_dir}/hub {remote_dir}/agent")
    # The hub writes its PocketBase data (beszel_data/) in WorkingDirectory and
    # the agent its own state, both as user beszel; without this the service
    # crash-loops with "mkdir beszel_data: permission denied".
    runners.ssh(
        env["OPSLAYER_MONITOR_SSH_USER"],
        env["OPSLAYER_OPS_HOST"],
        f"sudo chown -R beszel:beszel {remote_dir}/hub {remote_dir}/agent",
    )
    files = {
        "beszel/beszel-hub.service": "/etc/systemd/system/beszel-hub.service",
        "beszel/beszel-agent.service": "/etc/systemd/system/beszel-agent.service",
        "beszel/hub.env": f"{remote_dir}/hub/hub.env",
        "beszel/agent.env": f"{remote_dir}/agent/agent.env",
    }
    for tpl, dest in files.items():
        content = _template_path(tpl).read_text(encoding="utf-8")
        if tpl == "beszel/hub.env" and cfg.beszel_admin_email and cfg.beszel_admin_password:
            # USER_EMAIL/USER_PASSWORD let the hub create the first user on start
            # (no browser step); ignored once a user exists.
            content += (
                f"\nUSER_EMAIL={cfg.beszel_admin_email}\n"
                f"USER_PASSWORD={cfg.beszel_admin_password}\n"
            )
        rendered = _render(content, env)
        runners.remote_write(env["OPSLAYER_MONITOR_SSH_USER"], env["OPSLAYER_OPS_HOST"], dest, rendered)
    # agent.env / hub.env hold Beszel secrets: beszel-owned, 0600.
    runners.ssh(
        env["OPSLAYER_MONITOR_SSH_USER"],
        env["OPSLAYER_OPS_HOST"],
        f"sudo chown -R beszel:beszel {remote_dir} && sudo chmod 600 "
        f"{remote_dir}/agent/agent.env {remote_dir}/hub/hub.env",
    )
    runners.remote_systemctl(env["OPSLAYER_MONITOR_SSH_USER"], env["OPSLAYER_OPS_HOST"], "daemon-reload", "")
    runners.remote_systemctl(env["OPSLAYER_MONITOR_SSH_USER"], env["OPSLAYER_OPS_HOST"], "enable", "beszel-hub --now")
    runners.remote_systemctl(env["OPSLAYER_MONITOR_SSH_USER"], env["OPSLAYER_OPS_HOST"], "enable", "beszel-agent --now")
    return ["beszel-hub", "beszel-agent"]


def probe(*, cfg: Config | None = None) -> dict:
    """Validate the target box before any install or deploy. Fails closed.

    Checks SSH reachability, aarch64 arch, Debian-family OS (raspbian/raspberry
    pi os/ubuntu), apt-get presence, and sudo. Reports each check plus a soft
    memory/disk sanity. Returns {"ok": bool} - callers must not proceed on fail.
    """
    cfg = cfg or Config.load()
    if not cfg.ops_host:
        return _probe_fail("OPSLAYER_OPS_HOST is not set")
    user, host = cfg.monitor_ssh_user, cfg.ops_host

    checks: dict[str, dict] = {}

    code, out = runners.remote_status(user, host, "echo ready")
    checks["ssh"] = _ok(code == 0, out or "unreachable")
    if code != 0:
        return {"ok": False, "host": host, "checks": checks, "reason": "ssh-unreachable"}

    code, out = runners.remote_status(user, host, "uname -m")
    arch = out.strip().lower()
    checks["arch"] = _ok(arch in ("aarch64", "arm64", "armv8l"), arch or "unknown")

    code, out = runners.remote_status(
        user, host, "grep -E '^(ID|ID_LIKE)=' /etc/os-release 2>/dev/null"
    )
    os_id = out.lower()
    debian_family = any(t in os_id for t in ("debian", "ubuntu", "raspbian", "raspberry"))
    checks["os"] = _ok(debian_family, out.replace("\n", "; ") or "unknown")

    code, out = runners.remote_status(user, host, "command -v apt-get >/dev/null && echo yes")
    checks["apt"] = _ok(code == 0 and out.strip() == "yes", out.strip() or "missing")

    code, out = runners.remote_status(user, host, "sudo -n true 2>/dev/null && echo yes")
    checks["sudo"] = _ok(code == 0 and out.strip() == "yes", out.strip() or "unavailable")

    # soft sanity: enough memory for the Gatus source build, enough disk for deps
    code, out = runners.remote_status(user, host, "free -m | awk '/Mem:/{print $7}'")
    try:
        mem_avail = int(out.split()[-1]) if out else 0
    except ValueError:
        mem_avail = 0
    checks["memory_warn"] = _ok(mem_avail >= 1500, f"{mem_avail}MB avail")
    code, out = runners.remote_status(user, host, "df -m / | awk 'NR==2{print $4}'")
    try:
        disk_avail = int(out.split()[-1]) if out else 0
    except ValueError:
        disk_avail = 0
    checks["disk_warn"] = _ok(disk_avail >= 2048, f"{disk_avail}MB free")

    hard = [name for name, c in checks.items() if name not in ("memory_warn", "disk_warn") and not c["ok"]]
    ok = not hard
    return {"ok": ok, "host": host, "checks": checks, "reason": "hard-check-failed" if hard else None}


def _ok(good: bool, detail: str) -> dict:
    return {"ok": good, "detail": detail}


def _probe_fail(reason: str) -> dict:
    return {"ok": False, "reason": reason, "checks": {}}


def _installed(user: str, host: str, path: str) -> bool:
    code, out = runners.remote_status(user, host, f"test -x {path} && echo yes")
    return code == 0 and out.strip() == "yes"


def bootstrap(
    component: str = "all", *, force: bool = False, skip_probe: bool = False, cfg: Config | None = None
) -> dict:
    """One-time remote install of the monitoring binaries onto the target box.

    component: "gatus", "nut_exporter", "beszel", or "all". Runs a probe first
    (unless skip_probe) and refuses to install on a failed probe. Each step is
    idempotent - already-present binaries are skipped unless force=True.
    """
    cfg = cfg or Config.load()
    if component not in ("all", "gatus", "nut_exporter", "beszel"):
        raise runners.OpError(f"unknown component {component!r}")

    if not skip_probe:
        result = probe(cfg=cfg)
        if not result["ok"]:
            return {"result": "blocked", "reason": result.get("reason", "probe-failed"), "probe": result}

    user, host = cfg.monitor_ssh_user, cfg.ops_host
    steps: list[dict] = []

    if component in ("all", "beszel"):
        steps += _bootstrap_beszel(user, host, force)
    if component in ("all", "nut_exporter"):
        steps += _bootstrap_nut_exporter(user, host, force)
    if component in ("all", "gatus"):
        steps += _bootstrap_gatus(user, host, force)

    installed = [s["binary"] for s in steps if s["status"] == "installed"]
    skipped = [s["binary"] for s in steps if s["status"] == "skipped"]
    record("monitor.bootstrap", host, "ok", {"component": component, "installed": installed})
    return {
        "result": "ok",
        "host": host,
        "component": component,
        "installed": installed,
        "skipped": skipped,
        "steps": steps,
    }


def _bootstrap_beszel(user: str, host: str, force: bool) -> list[dict]:
    steps: list[dict] = []
    for name, path in (("beszel", "/usr/local/bin/beszel"), ("beszel-agent", "/usr/local/bin/beszel-agent")):
        asset = "beszel" if name == "beszel" else "beszel-agent"
        if _installed(user, host, path) and not force:
            steps.append({"binary": name, "status": "skipped", "detail": "already present"})
            continue
        url = f"https://github.com/henrygd/beszel/releases/latest/download/{asset}_linux_arm64.tar.gz"
        cmd = (
            f"cd /tmp && curl -sL '{url}' | tar -xz {asset} "
            f"&& sudo install -m 0755 {asset} {path} && rm -f {asset}"
        )
        runners.ssh(user, host, cmd)
        steps.append({"binary": name, "status": "installed", "detail": path})
    return steps


def _bootstrap_nut_exporter(user: str, host: str, force: bool) -> list[dict]:
    path = _BINARIES["nut_exporter"]
    if _installed(user, host, path) and not force:
        return [{"binary": "nut_exporter", "status": "skipped", "detail": "already present"}]
    url = "https://github.com/DRuggeri/nut_exporter/releases/download/v3.3.0/nut_exporter-v3.3.0-linux-arm64"
    cmd = f"cd /tmp && curl -sL -o nut_exporter '{url}' && sudo install -m 0755 nut_exporter {path} && rm -f nut_exporter"
    runners.ssh(user, host, cmd)
    return [{"binary": "nut_exporter", "status": "installed", "detail": path}]


def _bootstrap_gatus(user: str, host: str, force: bool) -> list[dict]:
    path = _BINARIES["gatus"]
    steps: list[dict] = []
    if _installed(user, host, path) and not force:
        return [{"binary": "gatus", "status": "skipped", "detail": "already present"}]

    code, out = runners.remote_status(user, host, "go version >/dev/null 2>&1 && echo yes")
    if not (code == 0 and out.strip() == "yes"):
        # no Go: try apt, fall back to the arm64 tarball
        code, out = runners.remote_status(user, host, "sudo apt-get install -y go >/dev/null 2>&1 && echo yes")
        if not (code == 0 and out.strip() == "yes"):
            cmd = (
                "cd /tmp && curl -sL -o go.tgz 'https://go.dev/dl/go1.22.0.linux-arm64.tar.gz' "
                "&& sudo tar -C /usr/local -xzf go.tgz && rm -f go.tgz && "
                "sudo ln -sf /usr/local/go/bin/go /usr/local/bin/go"
            )
            runners.ssh(user, host, cmd)
        steps.append({"binary": "go", "status": "installed", "detail": "toolchain"})
    else:
        steps.append({"binary": "go", "status": "skipped", "detail": "already present"})

    cmd = f"export PATH=$PATH:/usr/local/go/bin:$HOME/.local/bin && go install {_GATUS_REF} && sudo cp $(go env GOPATH)/bin/gatus {path}"
    runners.ssh(user, host, cmd, timeout=1800)
    steps.append({"binary": "gatus", "status": "installed", "detail": path})
    return steps


def stack_status(*, cfg: Config | None = None) -> dict:
    """Report systemctl active state for each deployed monitor service.

    Uses remote_status (not ssh) so a non-zero `systemctl is-active` exit is
    data, not an error: a unit that is activating/failed/absent reports its real
    state instead of being mislabelled "not-installed".
    """
    cfg = cfg or Config.load()
    statuses: dict[str, str] = {}
    for name, unit in _STACK.items():
        code, out = runners.remote_status(cfg.monitor_ssh_user, cfg.ops_host, f"systemctl is-active {unit}")
        state = out.splitlines()[0] if out else ""
        statuses[name] = state or ("unreachable" if code in (255, -1) else "unknown")
    return {"host": cfg.ops_host, "services": statuses}


def _http_json(
    url: str, *, method: str = "GET", body: dict | None = None, token: str | None = None, timeout: int = 15
) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", token)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8")
        except Exception:  # noqa: BLE001 - best-effort error body
            pass
        raise runners.OpError(f"HTTP {exc.code} for {url}: {detail[:200]}") from exc
    except urllib.error.URLError as exc:
        raise runners.OpError(f"cannot reach {url}: {exc.reason}") from exc
    return json.loads(raw) if raw else {}


def _hub_base(cfg: Config) -> str:
    return f"http://{cfg.ops_host}:{cfg.beszel_port}"


def _wait_hub(base: str, *, timeout: int = 90, interval: int = 2) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            _http_json(f"{base}/api/beszel/first-run", timeout=5)
            return True
        except runners.OpError:
            time.sleep(interval)
    return False


def _ensure_hub_user(base: str, cfg: Config) -> None:
    """Create the first hub user via the API if none exists (no browser step)."""
    state = _http_json(f"{base}/api/beszel/first-run")
    if not state.get("firstRun"):
        return
    if not (cfg.beszel_admin_email and cfg.beszel_admin_password):
        raise runners.OpError(
            "Beszel hub has no user yet; set OPSLAYER_BESZEL_ADMIN_EMAIL/PASSWORD "
            "or run: opslayer monitor beszel-init"
        )
    _http_json(
        f"{base}/api/beszel/create-user",
        method="POST",
        body={"email": cfg.beszel_admin_email, "password": cfg.beszel_admin_password},
    )
    record("monitor.beszel_user", cfg.ops_host, "ok", {"email": cfg.beszel_admin_email})


def _beszel_user_token(base: str, cfg: Config) -> str:
    resp = _http_json(
        f"{base}/api/collections/users/auth-with-password",
        method="POST",
        body={"identity": cfg.beszel_admin_email, "password": cfg.beszel_admin_password},
    )
    token = resp.get("token") or ""
    if not token:
        raise runners.OpError("Beszel auth failed (check OPSLAYER_BESZEL_ADMIN_EMAIL/PASSWORD)")
    return token


def _hub_public_key(user: str, host: str) -> str:
    code, out = runners.remote_status(user, host, f"sudo ssh-keygen -y -f {_BESZEL_HUB_KEY_PATH} 2>/dev/null")
    return out.strip() if code == 0 else ""


def beszel_sync(*, cfg: Config | None = None, env: dict[str, str] | None = None) -> dict:
    """Wire the Beszel agent with zero manual steps.

    Ensures the hub user exists, authenticates, mints (or reuses) a permanent
    universal token, reads the hub public key (SSH key file, fallback to the
    authenticated API), writes agent.env on the target, and restarts the agent.
    Idempotent: a token/key already present in config short-circuits the API.
    """
    cfg = cfg or Config.load()
    if not cfg.ops_host:
        raise runners.OpError("OPSLAYER_OPS_HOST is not set")
    user, host = cfg.monitor_ssh_user, cfg.ops_host
    base = _hub_base(cfg)

    key = cfg.beszel_key.strip()
    token = cfg.beszel_token.strip()
    source = "config"
    user_token = ""

    if not _wait_hub(base):
        raise runners.OpError(f"Beszel hub not reachable at {base}")
    if not token or not key:
        _ensure_hub_user(base, cfg)
        user_token = _beszel_user_token(base, cfg)
    if not key:
        key = _hub_public_key(user, host)
    if not key:
        key = (_http_json(f"{base}/api/beszel/info", token=user_token) or {}).get("key", "")
    if not key:
        raise runners.OpError(
            "could not read the Beszel hub public key (SSH key file and /api/beszel/info both empty)"
        )
    if not token:
        # Reuse the user's existing PERMANENT universal token if present; only
        # mint one when none exists. Minting unconditionally would hand the agent
        # a fresh token each run, and the hub dedupes systems by (token,
        # fingerprint) - so a new token registers a duplicate system every time.
        existing = _http_json(f"{base}/api/beszel/universal-token", token=user_token)
        if existing.get("permanent") and existing.get("token"):
            token = existing["token"]
            source = "universal-existing"
        else:
            resp = _http_json(f"{base}/api/beszel/universal-token?enable=1&permanent=1", token=user_token)
            token = resp.get("token") or ""
            if not resp.get("permanent") or not token:
                raise runners.OpError("Beszel did not return a permanent universal token")
            source = "universal-new"

    render_env = dict(env or _env(cfg))
    render_env["OPSLAYER_BESZEL_KEY"] = key
    render_env["OPSLAYER_BESZEL_TOKEN"] = token
    render_env["OPSLAYER_BESZEL_HUB_URL"] = cfg.beszel_hub_url
    content = _render(_template_path("beszel/agent.env").read_text(encoding="utf-8"), render_env)
    dest = "/opt/beszel/agent/agent.env"
    runners.remote_write(user, host, dest, content)
    runners.ssh(user, host, f"sudo chown beszel:beszel {dest} && sudo chmod 600 {dest}")
    runners.remote_systemctl(user, host, "restart", "beszel-agent")
    record("monitor.beszel_sync", host, "ok", {"key": "set", "token_source": source})
    return {
        "result": "ok",
        "host": host,
        "key": key if len(key) <= 24 else key[:19] + "..." + key[-8:],
        "token": "set",
        "token_source": source,
    }
