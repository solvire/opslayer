# opslayer

Control layer for the dtac.io homelab. One package, three transports:

- **CLI** (`opslayer`) - for the operator
- **MCP server** (`opslayer-mcp`) - for AI agents
- both wrap the same `operations/` functions; the logic exists once

Design rules:

- `operations/` holds the only real logic; `cli.py` and `mcp_server.py` are thin transports.
- Every command accepts `--json` and returns JSON-able dicts.
- External tools (kubectl, argocd, restic, upsc) are invoked via `runners/` subprocess
  wrappers - opslayer orchestrates, never reimplements.
- Every action logs an event (who/what/when/result) via `events.py`.

## Operation groups

| Module | Covers |
|---|---|
| `deploy` | app deploys, ArgoCD sync/rollback, manifest bumps |
| `networking` | DNS records, ingress/routing, port policy |
| `tunnel` | public exposure via dial-out tunnel (frp; provider seam for Cloudflare later) |
| `monitoring` | status, uptime, alerting |
| `nut` | UPS/power (server on pihole Zero, slaves elsewhere) |
| `cluster` | node lifecycle: drain, cordon, reboot, k3s join |
| `maintenance` | backup, restore, drills, upgrades, housekeeping |
| `secrets` | sops encrypt/rotate, credential status |

Roadmap (next target: the dtac.io / fartemis migration) lives in `docs/roadmap.md`.

## Install

```bash
pip install -e ".[dev,mcp]"
```

## Secret hygiene (public repo - non-negotiable)

- No hooks by design; instead the secret scan runs as part of the test suite
  (`pytest` - see `tests/test_secrets.py`) and on demand: `scripts/scan-secrets.sh`.
- Regenerate the baseline only after legitimate additions: `scripts/scan-secrets.sh --baseline`.
- Run a full scan before any push: `scripts/scan-secrets.sh`.
- Settings live in a repo-root `.env` (gitignored, never committed). Copy
  `.env.example` to `.env` or use `opslayer config set <key> <value>`.

## Status

v0.1 scaffold. Real operation implementations land as the M720q k3s node comes up.
As of 2026-09-22: node00 k3s up; scotttactical.com live over the frp tunnel
(operations/tunnel/ + networking verbs in GitHub d41185e). Next: dtac.io (fartemis)
per docs/roadmap.md.
# opslayer
