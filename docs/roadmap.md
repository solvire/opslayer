# opslayer ROADMAP

Grounded, not aspirational: every item traces to code in this repo or a feature
gap observed while operating the tunnel. This is a PUBLIC repo - no hostnames,
no IPs, no private deployment state, no internal checkpoint paths. Use generic
"a site" / "the edge" phrasing.

Legend: [U]=undone work, [Q]=quality-of-life.

## Context (framework-level)

opslayer controls a self-hosted edge (dial-out tunnel) + a home cluster (k3s +
ArgoCD GitOps). Multiple public sites ride one frpc deployment through the edge.
The tunnel provider is the piece that makes "expose a new site" repeatable.

## Undone work

1. **[U] `site add` composite command** - one verb for "new public site":
   `opselayer site add <host> <backend>` -> Route53 A/CNAME + frp proxy + frpc
   config + (for dynamic apps) the manifest bump + ArgoCD sync. Today a site is
   dns-upsert + tunnel-upsert called by hand.
   - Source: the frp provider's README/usage; observed manual two-step flow.
2. **[U] Dynamic multi-route add/remove** - upsert now MERGES routes into one
   frpc config (no longer clobbers), but there is no per-route add/remove
   without redeploying the whole Deployment, and no runtime route management.
   Ship a dynamic add/remove path (frp Store API or per-route apply).
   - Source: src/opselayer/operations/tunnel/frp.py.
3. **[U] Cloudflare tunnel provider** - the TunnelProvider registry seam exists
   for a `cloudflare.py` sibling (`available_providers()`), kept as the fallback
   if the self-owned edge is ever unwanted. Low priority given frp is proven.
   - Source: src/opselayer/operations/tunnel/__init__.py.
4. **[U] Edge monitoring + alerting** - frps exposes Prometheus metrics and a
   loopback dashboard; nothing polls them and there is no uptime alert for
   public sites. Add tunnel status polling + alert when a site stops returning
   200. The cutover decision was "OWN, script, and MONITOR the edge"; monitoring
   is the unwritten half.
   - Source: src/opselayer/operations/tunnel/frp.py (status/verify only).
5. **[U] sops for real credentials** - tokens are currently in the gitignored
   .env as plaintext. config.py notes "real credentials go to sops later";
   operations/secrets.py has encrypt/decrypt/status but no to-stdout encrypt
   (NotImplementedError). Wire sops; .env becomes a dev-only devcache.
   - Source: src/opselayer/config.py (secret note); src/opselayer/operations/secrets.py.
6. **[U] Live-cluster implementations for scaffolded groups** - deploy/monitoring/
   cluster were scaffolded against no live cluster. cluster.py docstring lists
   `reboot` but only drain/cordon/uncordon exist; deploy sync/rollback/history
   assume ArgoCD; monitoring has nodes/pods/summary stubs. Validate + complete
   against a live node.
   - Source: src/opselayer/operations/{cluster,deploy,monitoring}.py.

## Quality of life

7. **[Q] Fix MCP network_dns_list bug** - src/opselayer/mcp_server.py calls
   `operations.networking.dns_records(zone)` but the function is `dns_list`
   (networking.py). The MCP DNS-List tool would AttributeError.
   - Source: src/opselayer/mcp_server.py:93 vs src/opselayer/operations/networking.py.
8. **[Q] Centralize the frpc image ref** - `_IMAGE` is hardcoded in
   operations/tunnel/frp.py; the build script says to bump the version there
   AND in opslayer together. Two sources of truth for one tag invites drift.
   - Source: src/opselayer/operations/tunnel/frp.py (image const).
9. **[Q] Per-command `--json`** - `--json` is global-only (must precede the
   subcommand). A per-command attempt was reverted (a decorator cannot obscure
   the Typer callback signature). Nice-to-have: trailing `--json` per subcommand,
   done in a way that preserves Typer's signature introspection.
   - Source: src/opselayer/cli.py (global --json callback).
10. **[Q] `cluster relocate` workflow** - the frpc default backend floats (a
    k8s Service FQDN, not a pinned IP), so the tunnel survives node moves. But
    there is no one-command "drain a node, reschedule its workload pods to
    another" relocate. Multi-node makes this the relocation story.
    - Source: src/opselayer/operations/cluster.py; tunnel/frp.py default backend.

## Explicit non-goals / deferred

- DigitalOcean sites teardown - separate session (operator's most-expensive
  spend), may surface as an opslayer-scripted teardown.
- On-road VPN + home file sharing - sanctioned pattern is Tailscale (self-host
  notebook), deliberately out of tunnel/opslayer scope.