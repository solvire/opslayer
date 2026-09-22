# opslayer ROADMAP

Grounded, not aspirational: every item traces to a real file/doc/checkpoint. The
immediate target is the **dtac.io (fartemis repo)** migration - the next public site
over the frp tunnel the scotttactical cutover (2026-09-22) proved. Priorities are
ordered by what unblocks that, then platform QoL.

Legend: [U]=undone work, [Q]=quality-of-life.

## Next target: dtac.io (fartemis) migration

fartemis is a dynamic django/celery/beat/redis/postgres site (root domain dtac.io,
apex). The exposure story is already proven by scotttactical (apex A-record -> hub ->
frp, no port forwards). Its unique work is app conversion + DB migration, in its own
dedicated session. opslayer's contribution is making the exposure + deploy repeatable.

## Undone work (+ ordering so they unlock dtac.io)

1. **[U] `site add` composite command** - one verb for "new public site":
   `opslayer site add <host> <backend>` -> Route53 A/CNAME + frp proxy + frpc config
   + (for dynamic apps) the manifest bump + ArgoCD sync. scotttactical was
   dns-upsert + tunnel-upsert called by hand.
   - Source: insignia docs/checkpoints/20260922-frp-edge-cutover.md (site-add template).
2. **[U] Multi-route frp provider** - current frp.py is single-route: upsert_route
   overwrites the one `[[proxies]]` block; delete_route removes the whole app
   (Deployment+ConfigMap+Secret). Support N routes per frpc, dynamic add/remove
   without a redeploy. Shipping two sites (scotttactical + dtac.io) on one frpc
   makes this mandatory.
   - Source: src/opslayer/operations/tunnel/frp.py (upsert_route/delete_route).
3. **[U] Cloudflare tunnel provider** - the TunnelProvider registry seam exists for a
   `cloudflare.py` sibling (`available_providers()`), kept as the fallback if the
   self-owned edge is ever unwanted. Low priority given the frp path is proven.
   - Source: src/opslayer/operations/tunnel/__init__.py.
4. **[U] Edge monitoring + alerting** - frps on the hub exposes Prometheus metrics
   and a loopback dashboard; nothing polls them and there is no uptime alert for
   public sites. Add tunnel status polling + alert on the public site going non-200.
   The cutover decision was "OWN, script, and MONITOR the edge" - monitoring is the
   unwritten half.
   - Source: scotttactical docs/edge-deployment.md; frp-cutover decision.
5. **[U] sops for real credentials** - tokens (FRP_TOKEN, AWS) are currently in the
   gitignored .env as plaintext. config.py notes "real credentials go to sops later";
   operations/secrets.py has encrypt/decrypt/status but no to-stdout encrypt
   (NotImplementedError). Wire sops; .env becomes a dev-only devcache.
   - Source: src/opslayer/config.py (secret note); src/opslayer/operations/secrets.py.
6. **[U] Live-k3s implementations for scaffolded groups** - deploy/monitoring/cluster
   were scaffolded against no live cluster. cluster.py docstring lists `reboot` but
   only drain/cordon/uncordon exist; deploy sync/rollback/history assume ArgoCD;
   monitoring has nodes/pods/summary stubs. Validate + complete against node00.

## Quality of life

7. **[Q] Fix MCP network_dns_list bug** - src/opslayer/mcp_server.py calls
   `operations.networking.dns_records(zone)` but the function is `dns_list`
   (networking.py). The MCP DNS-List tool would AttributeError.
   - Source: src/opslayer/mcp_server.py:93 vs src/opslayer/operations/networking.py.
8. **[Q] Centralize the frpc image ref** - `_IMAGE` is hardcoded in
   operations/tunnel/frp.py; scripts/build-frpc.sh says to bump the version there
   AND in opslayer together. Two sources of truth for one tag invites drift.
   - Source: src/opslayer/operations/tunnel/frp.py (image const); scripts/build-frpc.sh.
9. **[Q] Per-command `--json`** - `--json` is global-only (must precede the
   subcommand). A per-command attempt was reverted this session (decorator cannot
   obscure the Typer callback signature). Nice-to-have: trailing `--json` per
   subcommand, done in a way that preserves Typer's signature introspection.
   - Source: src/opslayer/cli.py (global --json callback).
10. **[Q] `cluster relocate` workflow for node00-down** - frpc default backend floats
    (traefik.kube-system.svc, not a pinned IP), so the tunnel survives node moves.
    But there is no one-command "drain node00, reschedule its workload pods to an H5"
    relocate. H5s arriving makes this the relocation story the operator wanted.
    - Source: src/opslayer/operations/cluster.py; tunnel/frp.py default backend.

## Explicit non-goals / deferred

- DigitalOcean sites teardown - separate session (operator's most-expensive spend),
  may surface as an opslayer-scripted teardown.
- On-road VPN + home file sharing - sanctioned pattern is Tailscale (self-host
  notebook 3.4), deliberately out of tunnel/opslayer scope.