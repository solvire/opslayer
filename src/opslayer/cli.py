"""CLI transport. Thin over operations; every command takes --json."""

from __future__ import annotations

import json

import typer

from . import operations
from .config import Config, get_config
from .events import tail

app = typer.Typer(no_args_is_help=True, help="Control layer for the dtac.io homelab.")
deploy_app = typer.Typer(help="App deploys (ArgoCD).")
network_app = typer.Typer(help="DNS and ingress.")
monitor_app = typer.Typer(help="Cluster and service status.")
nut_app = typer.Typer(help="UPS/power status.")
cluster_app = typer.Typer(help="Node lifecycle.")
maintenance_app = typer.Typer(help="Backups and drills.")
events_app = typer.Typer(help="opslayer audit log.")
app.add_typer(deploy_app, name="deploy")
app.add_typer(network_app, name="network")
app.add_typer(monitor_app, name="monitor")
app.add_typer(nut_app, name="nut")
app.add_typer(cluster_app, name="cluster")
app.add_typer(maintenance_app, name="maintenance")
app.add_typer(events_app, name="events")

_json_state = {"enabled": False}


def _output(data: dict) -> None:
    if _json_state["enabled"]:
        typer.echo(json.dumps(data, indent=2, default=str))
    else:
        for key, value in data.items():
            typer.echo(f"{key}: {value}")


@app.callback()
def main(
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    _json_state["enabled"] = json_output


@deploy_app.command("sync")
def deploy_sync(app_name: str, wait: bool = True) -> None:
    _output(operations.deploy.sync(app_name, wait=wait))


@deploy_app.command("rollback")
def deploy_rollback(app_name: str, revision: str) -> None:
    _output(operations.deploy.rollback(app_name, revision))


@deploy_app.command("history")
def deploy_history(app_name: str) -> None:
    _output(operations.deploy.history(app_name))


@deploy_app.command("status")
def deploy_status(app_name: str) -> None:
    _output(operations.deploy.status(app_name))


@network_app.command("dns-list")
def network_dns_list(zone: str = "") -> None:
    _output(operations.networking.dns_list(zone or None))


@network_app.command("dns-zones")
def network_dns_zones() -> None:
    _output(operations.networking.list_zones())


@network_app.command("dns-upsert")
def network_dns_upsert(name: str, address: str, record_type: str = "A", ttl: int = 300) -> None:
    _output(operations.networking.dns_upsert(name, address, record_type, ttl))


@network_app.command("ingress")
def network_ingress(namespace: str = "default") -> None:
    _output(operations.networking.ingress_list(namespace))


@monitor_app.command("nodes")
def monitor_nodes() -> None:
    _output(operations.monitoring.nodes())


@monitor_app.command("pods")
def monitor_pods(namespace: str | None = None) -> None:
    _output(operations.monitoring.pods(namespace))


@monitor_app.command("summary")
def monitor_summary() -> None:
    _output(operations.monitoring.summary())


@nut_app.command("status")
def nut_status() -> None:
    _output(operations.nut.compact())


@nut_app.command("details")
def nut_details() -> None:
    _output(operations.nut.status())


@nut_app.command("get")
def nut_get(variable: str) -> None:
    _output(operations.nut.get(variable))


@cluster_app.command("cordon")
def cluster_cordon(node: str) -> None:
    _output(operations.cluster.cordon(node))


@cluster_app.command("uncordon")
def cluster_uncordon(node: str) -> None:
    _output(operations.cluster.uncordon(node))


@cluster_app.command("drain")
def cluster_drain(node: str) -> None:
    _output(operations.cluster.drain(node))


@maintenance_app.command("backup")
def maintenance_backup(tags: list[str] = typer.Option(None, "--tag")) -> None:
    _output(operations.maintenance.backup(tags))


@maintenance_app.command("snapshots")
def maintenance_snapshots(limit: int = 10) -> None:
    _output(operations.maintenance.snapshots(limit))


@maintenance_app.command("restore-check")
def maintenance_restore_check(snapshot: str, target: str) -> None:
    _output(operations.maintenance.restore_check(snapshot, target))


@events_app.command("tail")
def events_tail(limit: int = 20) -> None:
    _output({"events": tail(limit)})


config_app = typer.Typer(help="Read and write the repo-root .env (gitignored).")
app.add_typer(config_app, name="config")


@config_app.command("show")
def config_show() -> None:
    cfg: Config = get_config()
    _output({k: str(v) for k, v in cfg.__dict__.items()})


@config_app.command("path")
def config_path() -> None:
    from . import config as cfgmod

    _output({"path": str(cfgmod.env_path())})


@config_app.command("set")
def config_set(key: str, value: str) -> None:
    from . import config as cfgmod

    _output(cfgmod.set_value(key, value))


@config_app.command("unset")
def config_unset(key: str) -> None:
    from . import config as cfgmod

    _output(cfgmod.unset_value(key))


if __name__ == "__main__":
    app()
