# API reference

Prefix `/api`; inference compatibility prefix `/v1`. Responses are JSON. Body size is capped at 1 MiB, or 28 MiB on routes that carry media: document uploads, `/api/chat`, `/api/chat/stream`, `/v1/chat/completions`, `/api/extract` and `/api/datasets`. Browser sessions use HttpOnly cookies and `X-CSRF-Token`. Automation uses bearer tokens: Nuvora service tokens, or OIDC access tokens (JWTs) when SSO is configured.

## Authentication and roles

| Endpoint | Method | Result / permission |
|---|---|---|
| `/api/login` | POST | `{tenant, username, password}` → principal + CSRF; HttpOnly session cookie |
| `/api/session` | GET | Current principal and CSRF |
| `/api/auth/providers` | GET | Unauthenticated: `{password: true, oidc: {label, login} \| null}` |
| `/api/auth/oidc/login` | GET | 302 to the identity provider (code flow + PKCE); sets a signed state cookie |
| `/api/auth/oidc/callback` | GET | Validates state, exchanges the code, checks the ID token, provisions or updates the user, sets the session cookie and redirects to `/`. On failure redirects to `/?sso_error=…` |
| `/api/logout` | POST | Revoke the current session/token |
| `/api/password` | POST | `{current, new}`; changes your password and revokes your other sessions |
| `/api/tokens` | POST | Admin/developer: `{role: viewer\|developer, lifetime: seconds, label?}`; token returned once |
| `/api/tokens` | GET | Active service tokens (id, owner, role, label, created, expires). Admins see the workspace; others see their own |
| `/api/tokens/{id}` | DELETE | Revoke a service token. Owner or administrator |
| `/api/users` | GET / POST | Tenant administrator lists/creates members. Each listed member has `source: password \| sso` |
| `/api/users/{username}` | POST / DELETE | Administrator changes a member's `{role}` and/or `{groups}` (document access groups; SSO users get theirs from the identity provider on each login), or removes them. You cannot change or remove yourself, and the last administrator is protected. Demoting a member below developer revokes their service tokens |
| `/api/settings` | GET | Administrator: release, transport, worker state, provider allow-list, guardrail policy, today's budget and server limits |

Viewer: read/retrieve. Developer: inference, ingestion, prompt/agent/workflow creation, submissions. Approver: read and approval decisions. Admin: tenant configuration and user management; may also develop/approve, but never self-approve.

Service tokens may not carry approver/admin authority. A developer may mint viewer/developer tokens tied to their own identity. Keep a token out of shell history and source control.

## Resources

`GET /api/{collection}` returns `{items: [...]}`. `GET /api/{collection}/{id}` returns an object. All authenticated users may read their tenant collections.

Writable collections: `actions`, `models`, `knowledge`, `agents`, `prompts`, `policies`, `workflows`, `evaluations`, `recipes`, `routers`, `mcp_servers`, `connectors`. Actions, models, policies, MCP servers and connectors require admin; others require developer/admin. POST to the collection creates an object; POST to its ID updates using `expected_revision`. GET `/api/{collection}/{id}/versions` lists retained snapshots. DELETE requires admin and is only exposed for writable resources. Model deletion is refused for some direct resource references; there is no complete dependency garbage collector.

Read-only collections: `documents`, `datasets`, `memory`, `jobs`, `approvals`. Document ingestion, dataset creation, job submission and approval decision endpoints are separate. Documents with `groups` are visible only to members of those groups and to administrators. Dataset list and get responses omit the record content. A dataset can be deleted unless a recipe references it.

## Inference and knowledge

| Endpoint | Body | Behavior |
|---|---|---|
| POST `/api/chat` | `model` (a model id, `auto`, or `router:<id>`), `messages`, optional `max_tokens`, `temperature`, `cache` | Provider response + usage/evidence/cost. A message's `content` may be a list of `text` and `image_url` parts (at most 4 images, each data URL ≤ 7 MB, vision models only) |
| POST `/api/chat/stream` | Same as `/api/chat` | `text/event-stream`: one `start` (model, routing, cached), `delta` events with guardrail-checked text released at sentence boundaries, then `done` (usage, cost, latency, evidence class) or `error` (`{error}`) |
| GET `/v1/models` | — | OpenAI-shaped model list, including routers as `router:<id>` |
| POST `/api/images` | `prompt`, optional `model`, `n` (1–4), `size` | Images from a model with the `image` capability, stored as expiring artifacts (`NUVORA_ARTIFACT_TTL_DAYS`, default 7). Guardrails and the daily budget apply |
| POST `/v1/images/generations` | OpenAI-style `prompt`, `model`, `n`, `size`, `response_format` | `{data: [{b64_json}]}` or `[{url}]` |
| GET `/api/artifacts/{id}` | — | The artifact bytes. Owner or administrator only |
| POST `/v1/chat/completions` | OpenAI-style model/messages | Chat envelope. With `stream=true`, live OpenAI `chat.completion.chunk` frames ending in `data: [DONE]`. Validation errors before the first byte are normal HTTP errors |
| POST `/api/knowledge/{id}/upload` | `name`, `content_type`, `content_base64`, optional `metadata`, `groups` | Extracts text from txt, md, csv, json, html, docx or pdf (≤ 20 MB). Images go through OCR and audio through transcription (the knowledge base's `ocr_model` / `transcription_model`, or the `ocr` extra for local OCR); scanned PDFs fall back to OCR. The document records its `extraction` method. Errors: 413 too large, 415 unknown type, 422 unreadable, 503 extra or model missing |
| GET `/api/knowledge/{id}/documents` | — | Documents with content type, bytes, characters, chunk count and digest |
| DELETE `/api/documents/{id}` | — | Developer/admin: removes the document and its chunks (audited) |
| POST `/api/knowledge/{id}/ingest` | `name`, `text`, optional `source`, `chunk_size`, `overlap`, `metadata`, `groups` | New/replaced document, content digest |
| POST `/api/retrieve` | `knowledge_ids`, `query`, optional `top_k`, `filter` | Retrieved citation records the caller may see. `filter` matches document metadata, every key must match: `{key: value}` or `{key: {in: [values]}}` (at most 10 keys) |
| POST `/api/answer` | `knowledge_ids`, `question`, optional `model`, `top_k`, `filter` | Generation using supplied evidence, or refusal to invent absent evidence. Includes a `grounding` score when the policy sets a grounding threshold |
| POST `/api/guardrails/check` | `text`, optional `sources` (≤ 20 strings) | Policy verdict: word and regex filters, PII entities, injection, classifier, and contextual grounding against `sources` |
| POST `/api/extract` | `fields` (`{name: {type, description?}}`, 1–30), one of `document_id`, `text` or `image` (data URL), optional `model`, `min_confidence` (default 0.7) | 202 job. Returns typed fields with confidence; anything under `min_confidence` waits in an `extraction_review` approval |
| POST `/api/datasets` | `name`, `content` (JSONL in chat, completion or prompts format), optional `dry_run` | Validates 10–100,000 records (≤ 20 MiB), guard-checks each one, and returns stats. 200 for a dry run, 201 when stored |
| POST `/api/actions/import-openapi` | `spec` (OpenAPI 3 JSON), optional `base_url` (else the first server URL), `operations` (operationIds) | Admin: creates one typed action per GET/POST operation with flat inputs |

Knowledge objects optionally set `embedding_model` to a model of capability `embedding` (OpenAI-compatible or Ollama). Otherwise they use offline lexical retrieval. `rerank_model` (a chat model) reranks the top 20 candidates. Deleting a knowledge base deletes its documents.

## Runs

POST `/api/agents/{id}/run` body `{message, session?}`.

POST `/api/workflows/{id}/run` body `{text}`.

POST `/api/evaluations/{id}/run` body `{}`. An evaluation has `model`, `cases`, `pass_threshold`, optional `judge_model` and `knowledge_ids`. A case is `{input, contains?, excludes?, judge?: {criteria, min_score?}, grounded?}`. Results list each case with its `checks`, its judge and grounded verdicts (`score`, `reason`), and `passed`.

POST `/api/batches` body `{requests: [{model, messages, ...}]}` (1–100 requests).

POST `/api/prompts/{id}/experiment` body `{evaluation, variable?, variables?}`. Runs every variant of the prompt over an evaluation suite's cases, with `variable` receiving each case input. The result lists each arm (the control template plus every variant) with its score and cases, and names a `winner` only when a variant beats the control.

POST `/api/connectors/{id}/sync` body `{}`. Incremental sync of a web, S3 or Confluence connector: added, updated, unchanged and removed counts. Connectors with `interval_minutes` (15–10080) are also synced by the worker.

POST `/api/recipes/{id}/run` body `{}`. Sends a recipe with a dataset to the trainer (`NUVORA_TRAINER_URL`), polls it as `waiting_external`, and registers the resulting model.

All return a durable job with HTTP 202, as does `/api/extract`. `Idempotency-Key` is supported and scoped to the tenant. Reusing a key with a different payload returns 409. Poll `GET /api/jobs/{id}`. States: queued, running, waiting_approval, waiting_external (a Zyntra handoff or a training job), completed, failed, rejected, interrupted. Agent and workflow jobs record per-step timings, exported over OTLP when `NUVORA_OTEL_ENDPOINT` is set.

POST `/api/approvals/{id}/decide`: `{decision: approved|rejected, digest}`. Requires different-person approver/admin. No replay, wrong fingerprint or expired approval allowed.

POST `/api/evaluations/compare`: `{baseline: job_id, candidate: job_id}`. Requires two completed evaluation jobs with identical cases. Returns score difference and release verdict.

## Prompt, recipe, governance

POST `/api/prompts/{id}/render` body `{variables: {key: value}, variant?, subject?}`. Without `variant`, weighted variants are chosen stickily per `subject` (default: the caller).

POST `/api/recipes/{id}/export` returns a `TrainingRecipe` configuration for your own trainer.

GET `/api/overview`, `/api/usage`, `/api/audit`, `/api/tools` provide workspace summary, inference ledger, audit verification and the tools agents may use. Integration tools appear only when their system is configured.

## Integrations (administrator)

| Endpoint | Method | Result |
|---|---|---|
| `/api/integrations` | GET | Netra, Zyntra and Keep: configured, host and credential reference, plus model presets |
| `/api/integrations/{netra\|zyntra\|keep}/test` | POST | Calls the system's health endpoint; 503 when not configured |
| `/api/models/presets` | GET | Fabric, Gryvia, vLLM and Ollama presets |
| `/api/models/discover` | POST | `{provider, base_url, key_env?}` → `{models: [{id, capability}]}` from `/v1/models` or Ollama `/api/tags` |

Agent tools: `netra_status`, `netra_incidents`, `netra_flow_summary`, `netra_drop_explain` (read-only) and `run_code` (`{language: python\|bash, code}`, always staged as an approval and run in a Keep sandbox). Workflow step: `{type: handoff, action, inputs, scenario?, timeout_hours?}`.

`/api/audit` accepts `actor`, `action` (prefix, such as `approval.`) and `since` / `until` (Unix seconds). Verification always covers the whole chain, not just the filtered page.

GET `/api/usage/series?days=1..90` returns daily buckets (requests, tokens, cost, latency, cache hits), a per-model breakdown and today's budget. GET `/api/runs/stats` returns run counts by status and kind and median duration.

POST `/mcp` supports a small JSON-RPC tools subset: initialize, tools/list, tools/call. `list_models` and `search_knowledge` are read-only. It is not a full MCP streaming transport.

## Failure conventions

400 validation, 401 authentication, 403 role/origin/tool/host denial, 404 missing tenant object, 409 stale/expired/reused state, 413 oversized body, 422 guardrail or model capability refusal, 429 budget/concurrency throttle, 502 provider failure, 503 unavailable optional adapter. Some optimistic storage conflicts currently return 400.

Provider errors are sanitized so provider bodies or credentials do not become client errors.

## Enterprise action registry

An action object has `name`, `url`, `method` (`GET` or `POST`), optional `description` and `key_env`, and `input_schema` (object with scalar typed properties). Registering or editing one requires admin. POST actions always require approval; GET relies on the operator's assertion that the endpoint is read-only. Select agent tools named `action_<id>`, or create a workflow action step `{id, type: action, action_id, arguments}`. Arguments are pinned in the approved action. Never use GET endpoints that cause writes.

`/api/actions/import-openapi` creates these from an OpenAPI 3 document.

An `mcp_servers` object (admin) points at a remote MCP server's `url`, with an optional `key_env` and `readonly` flag. Its tools appear to agents as `mcp_<first 8 characters of the server id>_<tool>`. Calls to a server that is not `readonly` are staged as approvals, like POST actions.

External action results are size limited and guardrail checked. POST failures are not retried automatically because a timeout may hide a committed change. Always inspect the destination system before a new run.
