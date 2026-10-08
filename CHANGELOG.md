# Changelog

## Unreleased

- **Bedrock runtime operations (preview):** `Converse`, `ConverseStream`, `InvokeModel`, `InvokeModelWithResponseStream`, `CountTokens` and `GetFoundationModel` on the Bedrock-shaped front door, so `boto3.client('bedrock-runtime', endpoint_url=…)` works against Nuvora. They run on the same pipeline as `/v1/chat/completions` (guardrails, routing, budget, usage, audit; developer or admin role), with tool use, PNG/JPEG/WebP images, binary event streams, Nuvora/OpenAI and Anthropic-messages chat bodies and Nuvora/Titan embeddings bodies. `modelId` is a Nuvora model id, `router:<id>` or an ARN (`foundation-model/…`, `inference-profile/…`). Unmapped fields (`guardrailConfig`, `additionalModelRequestFields`, documents, `top_k`, …) are a `ValidationException` naming them. `CountTokens` is a characters/4 estimate and `stopReason` is derived. Stream failures after the first frame use lowerCamelCase exception types and `ModelErrorException` maps from provider 502. Tested with boto3/botocore and the offline demo provider only; not run against AWS or the `aws` CLI.
- **Inference completeness:** `POST /v1/embeddings` (OpenAI shape; guardrail, budget, usage and audit like chat). Chat accepts `tools`, `tool_choice`, `response_format` (`json_object`, `json_schema`), `top_p` and `stop` on `/v1/chat/completions`, `/api/chat` and `/api/chat/stream`, with `tool_calls` in responses and streams. OpenAI-compatible, Ollama (native) and the offline demo support them; the AWS adapter gains Converse `toolConfig` and tool-use blocks. Anything a provider cannot do is a 422 naming the parameter. Tested with stub servers and a mocked boto3 only; nothing run against live OpenAI, Ollama or Bedrock.
- **Live end-to-end check:** `scripts/e2e-live.py` runs chat, `/v1` streaming, embedding retrieval with filters, grounded answers, guardrails with a classifier model, a cascade router, a tool-using agent, vision, OCR and extraction against a real Ollama. All 16 checks passed on a CPU-only host.
- **Provider timeout:** `NUVORA_PROVIDER_TIMEOUT` (5–900 s, default 45) replaces the fixed 45-second provider timeout. Settings shows the value in effect.
- **Extraction:** bare field values from small models are kept at confidence 0 instead of being dropped, so they always count as low confidence.

## 0.3.0 — 2026-10-05

- **Guardrails v2:** policies gain word and regex filters, plus PII entities (email, IBAN with mod-97, card numbers with Luhn, SSN, IPv4, phone) that are masked or blocked. Also adds a lexical grounding score against retrieved sources, and an optional classifier model for hate, violence, sexual, self-harm, misconduct and prompt attacks, which fails closed. `POST /api/guardrails/check` tests a policy, and the console gets a policy editor. [Guardrails →](https://zyvorai.github.io/zyvor-nuvora/docs/operate/guardrails)
- **Routers:** a router cascades across 2–5 chat models. It escalates on an empty answer, an "I'm not sure" reply, or a judge score below `min_score`. Use it as `router:<id>` anywhere a model is accepted, including `/v1`. Cached prompt tokens are billed at `cached_input_price`, and usage shows savings. Policies can set `cache_ttl`. [Routing →](https://zyvorai.github.io/zyvor-nuvora/docs/operate/routing)
- **Prompt experiments:** prompts carry weighted variants with sticky per-subject rendering. An experiment runs each variant against an evaluation suite and compares scores.
- **Agents and tools:**
  - import an OpenAPI 3 document as typed actions
  - register remote MCP servers, whose writing tools wait for approval
  - long-term memory search and approved session summaries
  - per-step timing with an optional OTLP trace export and a run waterfall

  [Agents and tools →](https://zyvorai.github.io/zyvor-nuvora/docs/operate/agents-and-tools)
- **Multimodal:** chat accepts image content parts on OpenAI-compatible, Ollama and AWS providers. Uploads can OCR images and scans (a vision model or the `ocr` extra) and transcribe audio. `POST /api/extract` fills a typed field blueprint and can send low-confidence results to an approval. [Multimodal →](https://zyvorai.github.io/zyvor-nuvora/docs/operate/multimodal)
- **Connectors and access control:** web crawler, S3 and Confluence connectors, with scheduled incremental sync, restricted to `NUVORA_CONNECTOR_HOSTS`. Documents carry metadata for retrieval filters, plus user groups that limit who can retrieve them. [Connectors →](https://zyvorai.github.io/zyvor-nuvora/docs/operate/connectors)
- **Training:** validated JSONL datasets. LoRA, QLoRA and distillation jobs run on your own trainer (`NUVORA_TRAINER_URL`). Nuvora polls each job and registers the resulting model. [Training →](https://zyvorai.github.io/zyvor-nuvora/docs/operate/training)
- **Images:** an `image` model capability with `image_price`, `POST /api/images` and `/v1/images/generations`, and expiring artifacts. Adds a Playground **Images** tab and a `generate_image` workflow step. [Images →](https://zyvorai.github.io/zyvor-nuvora/docs/operate/images)
- **Helm:** `env` sets extra `NUVORA_*` variables and `envFromSecret` loads credentials from a Secret. Rendering rejects other variable names and inline `NUVORA_SECRET_*` values.
- **Branding:** the managed-cloud vendor name is gone from the code and copy. The provider is `aws`, and `bedrock` is still accepted as an alias.
- **Website:** a redesigned homepage and seven new Operate guides.

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
- **Streaming:** `/v1/chat/completions` streams live from the provider, and the AWS provider uses `converse_stream`.
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
