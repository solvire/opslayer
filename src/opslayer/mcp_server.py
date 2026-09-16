"""MCP transport. Exposes the same operations as agent tools.

Run: opslayer-mcp (or `python -m opslayer.mcp_server`).
The real deployment wires this behind the ops controller's API-key + SSH guard;
see docs/checkpoints/20260915-pi4-ops-controller-flash.md for the posture spec.
"""

from __future__ import annotations

from . import operations
from .config import get_config
from .events import tail

try:
    from fastmcp import FastMCP
except ModuleNotFoundError as exc:  # pragma: no cover
    raise SystemExit(
        "fastmcp is not installed. Install with: pip install 'opslayer[mcp]'"
    ) from exc

mcp = FastMCP("opslayer")


@mcp.tool()
def nut_status() -> dict:
    """UPS state for ups01 (charge, load, runtime, online/battery)."""
    return operations.nut.status()


@mcp.tool()
def deploy_sync(app: str, wait: bool = True) -> dict:
    """Trigger an ArgoCD app sync (optionally waiting for health)."""
    return operations.deploy.sync(app, wait=wait)


@mcp.tool()
def deploy_rollback(app: str, revision: str) -> dict:
    """Roll an ArgoCD app back to a revision."""
    return operations.deploy.rollback(app, revision)


@mcp.tool()
def deploy_history(app: str) -> dict:
    """Revision history for an ArgoCD app."""
    return operations.deploy.history(app)


@mcp.tool()
def monitor_nodes() -> dict:
    """Cluster node overview."""
    return operations.monitoring.nodes()


@mcp.tool()
def monitor_pods(namespace: str | None = None) -> dict:
    """Pods across all namespaces or one namespace."""
    return operations.monitoring.pods(namespace)


@mcp.tool()
def cluster_cordon(node: str) -> dict:
    """Cordon a node (no new pods scheduled)."""
    return operations.cluster.cordon(node)


@mcp.tool()
def cluster_uncordon(node: str) -> dict:
    """Uncordon a node."""
    return operations.cluster.uncordon(node)


@mcp.tool()
def cluster_drain(node: str) -> dict:
    """Drain a node safely before maintenance or shutdown."""
    return operations.cluster.drain(node)


@mcp.tool()
def maintenance_backup(tags: list[str] | None = None) -> dict:
    """Run a restic backup."""
    return operations.maintenance.backup(tags)


@mcp.tool()
def maintenance_restore_check(snapshot: str, target: str) -> dict:
    """Restore a snapshot to a scratch target (monthly drill)."""
    return operations.maintenance.restore_check(snapshot, target)


@mcp.tool()
def network_dns_list(zone: str = "") -> dict:
    """List Route53 record sets for a zone."""
    return operations.networking.dns_records(zone)


@mcp.tool()
def network_ingress(namespace: str = "default") -> dict:
    """List k8s ingresses in a namespace."""
    return operations.networking.ingress_list(namespace)


@mcp.tool()
def opslayer_events(limit: int = 20) -> dict:
    """Recent opslayer actions (audit tail)."""
    return {"events": tail(limit)}


@mcp.tool()
def opslayer_config() -> dict:
    """Effective opslayer configuration (secrets excluded)."""
    return {k: str(v) for k, v in get_config().__dict__.items()}


if __name__ == "__main__":
    mcp.run()
