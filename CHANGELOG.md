# Changelog

## Unreleased

- **Console:** the console now uses the Zyvor Apple UX contract ported from Netra:
  - Apple tokens, light by default with dark one click away
  - grouped mega-menu navigation over 17 pages
  - a story-tier Overview, `PageHero` headers, and toolbar-and-table browse pages
  - a Netra-style sign-in page
- **Deploy:** `scripts/deploy-remote.sh` builds on a k3s host with podman, imports the image, and installs with Helm. It serves HTTPS on NodePort 30789 with a persistent self-signed certificate and runs deploy guards: a disk check, an image re-import, and a rollout wait.
- **Helm:** adds `service.type` and `service.nodePort`, direct TLS through `tls.existingSecret` (with HTTPS probes), `demo`, and `allowDemoPassword`.
- **Auth:** the bootstrap administrator can use the demo password `Admin@321` when `NUVORA_ALLOW_DEMO_PASSWORD=1` is set. Every other password still needs 12–256 characters.
- **Server:** the TLS handshake now runs per connection, so one stalled client can't block the accept loop.
- **Tests:** the browser smoke runs against live instances: every page, light and dark, 1440px and 390px. CI adds helm lint/template, shellcheck, and deploy-guard checks.
- **Docs:** a Docusaurus site on GitHub Pages, social and README artwork rendered from HTML, a deploy guide, and the UX contract.

## 0.1.0 — 2026-10-05

Initial evaluation release: tenant-scoped AI application API and 16-view console, model adapters, lexical/optional-semantic retrieval, registered agents, reviewed workflows, prompt snapshots, deterministic evaluation, guardrails, cache/batch inference, usage ledger, SDK/CLI, MCP tools subset, and audit evidence.

External training recipes are exported but not executed. Model hosting, Keep isolation, OIDC, distributed HA, multimodal extraction, formal reasoning and broad safety classifiers remain roadmap work.
