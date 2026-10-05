# Changelog

## 0.2.0 — 2026-10-05

- **Single sign-on:** OIDC authorization code flow with PKCE (`nuvora/oidc.py`). Adds bearer JWT verification against the issuer JWKS (`sso` extra), just-in-time users, group-to-role mapping on every login, and an optional tenant claim. The sign-in page gains a **Sign in with SSO** button. Configure with `NUVORA_OIDC_*` or the Helm `oidc.*` values.
- **PostgreSQL:** `nuvora/db.py` puts SQLite and PostgreSQL behind one adapter, selected with `NUVORA_DATABASE_URL` (`postgres` extra). Also adds:
  - versioned migrations under an advisory lock
  - atomic job claims (`FOR UPDATE SKIP LOCKED`) and worker heartbeats, so only jobs whose worker died become interrupted
  - per-tenant advisory locks on audit appends
  - a database-backed login throttle shared by replicas
  - `scripts/migrate-sqlite-to-postgres.py`
- **Helm:** `replicas` and `database.urlSecret` (no PVC, rolling updates). Rendering refuses several replicas on SQLite, or with SSO but no client secret.
- **Integrations:** Fabric/Gryvia model presets and model discovery. Netra read tools (`netra_status`, `netra_incidents`, `netra_flow_summary`, `netra_drop_explain`). A workflow `handoff` step that parks a run as `waiting_external` until Zyntra decides. Keep `run_code`, executed only after a different person approves the exact code. The Settings page adds an Integrations card with connection tests.
- **Documents:** file upload for txt, md, json, csv, html and docx (PDF with the `pdf` extra), with a per-route body limit. Deleting a document removes it from every knowledge base.
- **Evaluations and retrieval:** LLM-judge and grounded cases, a case editor, and per-case reasons in Runs. Adds Ollama embeddings, optional LLM rerank, and stemming with stopwords. A recall@k fixture test guards retrieval quality.
- **Streaming:** `/v1/chat/completions` streams live from the provider, and Bedrock uses `converse_stream`.
- **Release:** optional extras (`pdf`, `sso`, `postgres`, `aws`, `all`) with the core still standard-library only. The image bundles every extra. A tag workflow publishes the ghcr.io image, wheel, Helm chart and SBOM. SPDX headers are checked in CI.
- **Deploy:** `deploy-remote.sh` generates a random administrator password on the first deploy. The demo login `Admin@321` is opt-in with `NUVORA_DEMO_PASSWORD=1`.
- **CI:** a PostgreSQL job runs the backend suite and a migration round trip against postgres:16.
- **Docs:** new Operate guides for SSO, PostgreSQL, integrations, and documents and evaluations.

- **License:** Nuvora moves from Apache-2.0 to the Zyvor Production License v1.0 (`LicenseRef-Zyvor-Production-1.0`), matching Netra. Non-production use stays free; production use needs a commercial license. Adds `NOTICE` and `LICENSES/`.

- **Console UX overhaul:**
  - a split-screen sign-in
  - a ⌘K command palette and keyboard shortcuts
  - a playground with conversations, streaming and Stop, model compare and citation hover cards
  - an onboarding checklist and guided empty states
  - resource drawers with history, diff and JSON, editing for every writable kind, and `#kind/id` deep links
  - a workflow DAG canvas and visual builder, and a run inspector with inline approval
  - usage, overview and evaluation charts
  - a notification bell, profile menu, password change, API keys and Settings pages, member role editing, and evidence filters with CSV export
- **API:** `POST /api/chat/stream` (SSE with guardrail-checked deltas), `POST /api/password`, `GET`/`DELETE /api/tokens`, `POST`/`DELETE /api/users/{username}`, `GET /api/settings`, `GET /api/usage/series`, `GET /api/runs/stats`, and audit filters.
- **Security:** demoting a member below developer revokes their service tokens. Changing your password revokes your other sessions.

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
