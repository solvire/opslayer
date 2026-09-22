# Checkpoint: tunneling operation group (frp) - scotttactical.com cutover

**Date:** 2026-09-22
**Goal:** Add a provider-seam `tunnel` operation group to opslayer and use it to
expose scotttactical.com to the public internet over a self-owned frp edge on an
already-paid EC2 t4g.small - zero port forwards, all DNS on Route53, no SSH.
**Status:** SHIPPED + verified. opslayer tunnel verbs built + tests green; the
cutover applied and public https://scotttactical.com serves the cluster
(Hugo 0.166.0). Deployed from this code.

## Why a tunnel group (and why provider-seam)

The DNS side already uses a pluggable provider registry (Route53 default, Cloudflare
later). Tunneling has the same shape: one host routed to a home backend via a dial-out
connector. This adds the same seam so a future `cloudflare` provider can replace `frp`
without touching callers (CLI / MCP / agents all dispatch through get_provider).

## Files added / changed

- ADDED `src/opslayer/operations/tunnel/__init__.py` - TunnelProvider registry
  (list_routes / upsert_route / delete_route / status / verify), register() /
  get_provider() / available_providers(). OPSLAYER_TUNNEL_PROVIDER selects; default frp.
- ADDED `src/opslayer/operations/tunnel/frp.py` - frp provider. Renders frpc.toml with
  `{{ .Envs.FRP_TOKEN }}` templating (token never in git); reconciles ConfigMap
  `frpc-config` + Secret `frpc-token` + Deployment `frpc` via `kubectl apply -f -`
  (no SSH). Supports hostHeaderRewrite. Hardened deployment: runAsNonRoot, uid/gid
  65534, drop ALL caps, readOnlyRootFilesystem + emptyDir scratch.
- CHANGED `src/opslayer/config.py` - keys OPSLAYER_TUNNEL_PROVIDER / FRP_SERVER /
  FRP_PORT / FRP_TOKEN; frp_port int-cast on load.
- CHANGED `src/opslayer/runners.py` - run()/kubectl() accept stdin (input=) for
  `kubectl apply -f -`.
- CHANGED `src/opslayer/operations/networking.py` - tunnel facade verbs.
- CHANGED `src/opslayer/cli.py` - network tunnel-list/upsert/delete/status/verify.
- CHANGED `src/opslayer/mcp_server.py` - tunnel_* agent tools.
- CHANGED `.env.example` - tunnel keys documented (never the token value).
- CHANGED `.gitignore` / `.secrets.baseline` - keep .env / tokens out.
- ADDED `tests/test_tunnel.py` - 13 tests (token-not-in-config, target resolution,
  hostHeaderRewrite, dispatch, graceful-not-deployed).
- tests: full suite 31 passed.

## The opslayer verb that deploys the route

```bash
opslayer --json network tunnel-upsert scotttactical.com \
  traefik.kube-system.svc.cluster.local \
  --domain scotttactical.com --domain www.scotttactical.com \
  --rewrite-host scotttactical.dtac.io
```

Renders frpc.toml (edge OPSLAYER_FRP_SERVER, token via Secret), apply ConfigMap +
Secret + Deployment. Read-only: tunnel-status / tunnel-list / tunnel-verify.

## Failures hit during the live cutover (recorded, not relitigated)

- nginx had no `listen`/cert -> 443 served hub.kidecon.me. Fixed with certbot --nginx.
- frpc forwarded Host scotttactical.com to Traefik (which routes scotttactical.dtac.io)
  -> 404. Fixed with --rewrite-host.
- frpc CrashLoop: dial hub:7000 i/o timeout - the hub EC2 security group had no
  inbound TCP 7000. Added it. Remember on any new box.

## Out of scope

- The hub edge itself (frps systemd, nginx, certbot, Route53 A record) lives in the
  scotttactical repo's docs/edge-deployment.md - this checkpoint is the opslayer side.
- DigitalOcean sites and on-road VPN/file-sharing are separate sessions.