"""frp tunnel provider.

Owns the home-side frpc Deployment + ConfigMap + token Secret in the cluster.
This provider reconciles the frpc proxy config that dial-channels a public host
to a k8s Service/DNS backend, outbound from the home cluster to the edge
(frps on the hub).

No SSH, no hand-run kubectl: every verb goes through the runners and returns
plain JSON-able dicts. The shared tunnel token (OPSLAYER_FRP_TOKEN) is a k8s
Secret (name frpc-token) injected into frpc via an env reference, using frp's
`{{ .Envs.FRP_TOKEN }}` templating in the ConfigMap. The token is never written
into the versioned ConfigMap and never into git.

State lives only on the cluster (ConfigMap + Deployment + Secret) driven by the
OPSLAYER_FRP_* settings in the gitignored .env. Nothing is kept in an untracked
local file.
"""

from __future__ import annotations

import json

from ... import runners
from ...config import Config
from ...events import record
from . import register

_NAMESPACE = "default"
_APP_NAME = "frpc"
_TOKEN_SECRET = "frpc-token"
_CONFIG_CM = "frpc-config"
_IMAGE = "ghcr.io/solvire/frpc:0.71.0"
_DEFAULT_BACKEND = "traefik.kube-system.svc.cluster.local"


def _backend_target(target: str) -> str:
    """Normalize the frpc localIP: a k8s Service DNS name or a host:port.

    Accepts a bare Service name (aimed at default ns), a dotted FQDN, an
    http(s) URL (strips scheme+port into localIP + localPort), or host:port.
    Default (empty) points at Traefik so it floats across node00/H5s.
    """
    return target or _DEFAULT_BACKEND


def _split_target(target: str) -> tuple[str, int]:
    """Return (localIP, localPort) from a target string."""
    backend = _backend_target(target)
    if "://" in backend:
        scheme, _, rest = backend.partition("://")
        host = rest.split("/", 1)[0]
        if host.endswith(":"):
            host = host.rstrip(":")
        if ":" in host and host.count(":") == 1:
            addr, _, port = host.rpartition(":")
            try:
                return addr, int(port)
            except ValueError:
                pass
        return host, 80
    if backend.count(":") == 1:
        addr, _, port = backend.rpartition(":")
        try:
            return addr, int(port)
        except ValueError:
            return backend, 80
    return backend, 80


def _proxy_block(hosts: list[str], target: str, rewrite_host: str | None = None) -> str:
    """Render ONE frpc.toml `[[proxies]]` block for an http route.

    The token is NOT rendered here; frp reads it from the environment in the
    container (secretKeyRef -> FRP_TOKEN), keeping it out of the versioned CM.
    """
    domains = ", ".join(f'"{h}"' for h in hosts)
    local_ip, local_port = _split_target(target)
    rewrite = ""
    if rewrite_host:
        rewrite = f'hostHeaderRewrite = "{rewrite_host}"\n'
    return (
        "[[proxies]]\n"
        f"name = \"{hosts[0]}\"\n"
        "type = \"http\"\n"
        f"localIP = \"{local_ip}\"\n"
        f"localPort = {local_port}\n"
        "customDomains = [" + domains + "]\n"
        + rewrite
        + "transport.useEncryption = true\n"
    )


def _toml(cfg: Config, hosts: list[str], target: str, rewrite_host: str | None = None) -> str:
    """Back-compat: single-route config (header + one proxy)."""
    return _render_config(cfg, [_proxy_block(hosts, target, rewrite_host)])


def _render_config(cfg: Config, proxy_blocks: list[str]) -> str:
    """Full frpc.toml: shared header + one [[proxies]] block per route."""
    return (
        f"serverAddr = \"{cfg.frp_server}\"\n"
        f"serverPort = {cfg.frp_port}\n"
        "auth.method = \"token\"\n"
        "auth.token = \"{{ .Envs.FRP_TOKEN }}\"\n\n"
        + "\n".join(proxy_blocks)
        + "\n"
    )


def _parse_proxy_names(toml: str) -> set[str]:
    """Return the set of route names (proxy `name =` values) in a config string."""
    import re
    return set(re.findall(r"^name = \"([^\"]+)\"", toml, re.MULTILINE))


def _configmap_manifest(toml: str) -> dict:
    return {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {"name": _CONFIG_CM, "labels": {"app.kubernetes.io/name": _APP_NAME}},
        "data": {"frpc.toml": toml},
    }


def _secret_manifest(token: str) -> dict:
    import base64
    return {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {"name": _TOKEN_SECRET, "labels": {"app.kubernetes.io/name": _APP_NAME}},
        "type": "Opaque",
        "data": {"FRP_TOKEN": base64.b64encode(token.encode()).decode()},
    }


def _deployment_manifest() -> dict:
    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": _APP_NAME, "labels": {"app.kubernetes.io/name": _APP_NAME}},
        "spec": {
            "replicas": 1,
            "selector": {"matchLabels": {"app.kubernetes.io/name": _APP_NAME}},
            "template": {
                "metadata": {"labels": {"app.kubernetes.io/name": _APP_NAME}},
                "spec": {
                    "imagePullSecrets": [{"name": "ghcr-pull"}],
                    "containers": [
                        {
                            "name": "frpc",
                            "image": _IMAGE,
                            "args": ["-c", "/etc/frpc/frpc.toml"],
                            "ports": [{"containerPort": 8080, "name": "http"}],
                            "env": [
                                {
                                    "name": "FRP_TOKEN",
                                    "valueFrom": {
                                        "secretKeyRef": {"name": _TOKEN_SECRET, "key": "FRP_TOKEN"}
                                    },
                                }
                            ],
                            "volumeMounts": [
                                {"name": "config", "mountPath": "/etc/frpc", "readOnly": True},
                                {"name": "scratch", "mountPath": "/tmp"},
                            ],
                            "resources": {
                                "requests": {"cpu": "10m", "memory": "16Mi"},
                                "limits": {"cpu": "200m", "memory": "64Mi"},
                            },
                            "securityContext": {
                                "allowPrivilegeEscalation": False,
                                "readOnlyRootFilesystem": True,
                                "runAsNonRoot": True,
                                "runAsUser": 65534,
                                "runAsGroup": 65534,
                                "capabilities": {"drop": ["ALL"]},
                            },
                        }
                    ],
                    "volumes": [
                        {"name": "config", "configMap": {"name": _CONFIG_CM}},
                        {"name": "scratch", "emptyDir": {}},
                    ],
                },
            },
        },
    }


@register("frp")
class FrpProvider:
    def __init__(self, cfg: Config | None = None):
        self.cfg = cfg or Config.load()

    def _ensure_server(self, cfg: Config) -> None:
        if not cfg.frp_server:
            raise LookupError("OPSLAYER_FRP_SERVER is not set (the edge/tunnel hub address).")
        if not cfg.frp_token:
            raise LookupError("OPSLAYER_FRP_TOKEN is not set (shared tunnel auth token).")

    def list_routes(self, *, cfg: Config | None = None) -> dict:
        cfg = cfg or self.cfg
        toml = self._read_config_toml(cfg)
        return {
            "provider": "frp",
            "namespace": _NAMESPACE,
            "routes": sorted(_parse_proxy_names(toml)),
            "config": toml,
        }

    def _read_config_toml(self, cfg: Config) -> str:
        """Current frpc.toml from the live ConfigMap ('' if none)."""
        try:
            out = runners.kubectl(["get", "cm", _CONFIG_CM, "-n", _NAMESPACE, "-o", "json"])
            return json.loads(out).get("data", {}).get("frpc.toml", "")
        except Exception:  # noqa: BLE001 - not deployed yet
            return ""

    def upsert_route(self, name: str, target: str, domains: list[str] | None, *, cfg: Config | None = None, rewrite_host: str | None = None) -> dict:
        cfg = cfg or self.cfg
        self._ensure_server(cfg)
        hosts = domains or [name]

        # Multi-route: read the live config, drop any existing block for THIS
        # route name, then append the new block. Other routes are preserved.
        current = self._read_config_toml(cfg)
        new_block = _proxy_block(hosts, target, rewrite_host)
        kept = ""
        if current:
            # split existing proxies by [[proxies]] headers, keep non-matching names
            import re
            blocks = re.split(r"(?=^\[\[proxies\]\]$)", current, flags=re.MULTILINE)
            for blk in blocks:
                if blk.startswith("[[proxies]]"):
                    m = re.search(r'^name = "([^"]+)"', blk, re.MULTILINE)
                    if m and m.group(1) == hosts[0]:
                        continue  # replace this route
                    kept += blk
        toml = _render_config(cfg, [b for b in (kept, new_block) if b.strip()])

        manifests = [
            _configmap_manifest(toml),
            _secret_manifest(cfg.frp_token),
            _deployment_manifest(),
        ]
        combined = "\n---\n".join(json.dumps(m) for m in manifests)
        runners.kubectl(["apply", "-n", _NAMESPACE, "-f", "-"], input=combined, timeout=60)
        entry = record(
            "tunnel.upsert_route", name, "ok",
            {"backend": target, "domains": hosts, "rewrite_host": rewrite_host},
        )
        return {
            "result": "ok",
            "route": name,
            "backend": target,
            "domains": hosts,
            "rewrite_host": rewrite_host,
            "routes": sorted(_parse_proxy_names(toml)),
            "deployed": [_TOKEN_SECRET, _CONFIG_CM, _APP_NAME],
            "event": entry,
        }

    def delete_route(self, name: str, *, cfg: Config | None = None) -> dict:
        cfg = cfg or self.cfg
        try:
            runners.kubectl(["delete", "deploy", _APP_NAME, "-n", _NAMESPACE, "--ignore-not-found"])
            runners.kubectl(["delete", "cm", _CONFIG_CM, "-n", _NAMESPACE, "--ignore-not-found"])
            runners.kubectl(["delete", "secret", _TOKEN_SECRET, "-n", _NAMESPACE, "--ignore-not-found"])
        except Exception as exc:  # noqa: BLE001 - surface as one clean result
            raise RuntimeError(f"delete_route failed: {exc}") from exc
        entry = record("tunnel.delete_route", name, "ok")
        return {"result": "ok", "route": name, "event": entry}

    def status(self, *, cfg: Config | None = None) -> dict:
        cfg = cfg or self.cfg
        out = ""
        try:
            out = runners.kubectl(["get", "deploy", _APP_NAME, "-n", _NAMESPACE, "-o", "wide"])
        except Exception:  # noqa: BLE001 - not deployed yet
            out = "frpc: not deployed"
        return {"provider": "frp", "namespace": _NAMESPACE, "deployment": out}

    def verify(self, public_url: str, *, cfg: Config | None = None) -> dict:
        cfg = cfg or self.cfg
        out = runners.run(
            ["curl", "-sk", "-o", "/dev/null", "-w", "%{http_code}", public_url], timeout=30
        )
        return {"url": public_url, "http_code": out}