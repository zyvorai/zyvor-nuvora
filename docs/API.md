# API reference

Prefix `/api`; inference compatibility prefix `/v1`. Responses are JSON. Body size is capped at 1 MiB, or 28 MiB for document uploads. Browser sessions use HttpOnly cookies and `X-CSRF-Token`. Automation uses bearer tokens: Nuvora service tokens, or OIDC access tokens (JWTs) when SSO is configured.

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
| `/api/users/{username}` | POST / DELETE | Administrator changes a member's `{role}` or removes them. You cannot change or remove yourself, and the last administrator is protected. Demoting a member below developer revokes their service tokens |
| `/api/settings` | GET | Administrator: release, transport, worker state, provider allow-list, guardrail policy, today's budget and server limits |

Viewer: read/retrieve. Developer: inference, ingestion, prompt/agent/workflow creation, submissions. Approver: read and approval decisions. Admin: tenant configuration and user management; may also develop/approve, but never self-approve.

Service tokens may not carry approver/admin authority. A developer may mint viewer/developer tokens tied to their own identity. Keep a token out of shell history and source control.

## Resources

`GET /api/{collection}` returns `{items: [...]}`. `GET /api/{collection}/{id}` returns an object. All authenticated users may read their tenant collections.

Writable collections: `actions`, `models`, `knowledge`, `agents`, `prompts`, `policies`, `workflows`, `evaluations`, `recipes`. Actions/models/policies require admin; others require developer/admin. POST to the collection creates an object; POST to its ID updates using `expected_revision`. GET `/api/{collection}/{id}/versions` lists retained snapshots. DELETE requires admin and is only exposed for writable resources. Model deletion is refused for some direct resource references; there is no complete dependency garbage collector.

Read-only collections: `documents`, `memory`, `jobs`, `approvals`. Document ingestion, job submission and approval decision endpoints are separate.

## Inference and knowledge

| Endpoint | Body | Behavior |
|---|---|---|
| POST `/api/chat` | `model`, `messages`, optional `max_tokens`, `temperature`, `cache` | Provider response + usage/evidence/cost |
| POST `/api/chat/stream` | Same as `/api/chat` | `text/event-stream`: one `start` (model, routing, cached), `delta` events with guardrail-checked text released at sentence boundaries, then `done` (usage, cost, latency, evidence class) or `error` (`{error}`) |
| GET `/v1/models` | — | OpenAI-shaped model list |
| POST `/v1/chat/completions` | OpenAI-style model/messages | Chat envelope. With `stream=true`, live OpenAI `chat.completion.chunk` frames ending in `data: [DONE]`. Validation errors before the first byte are normal HTTP errors |
| POST `/api/knowledge/{id}/upload` | `name`, `content_type`, `content_base64` | Extracts text from txt, md, csv, json, html, docx or pdf (≤ 20 MB), then ingests it. Errors: 413 too large, 415 unknown type, 422 unreadable, 503 PDF extra missing |
| GET `/api/knowledge/{id}/documents` | — | Documents with content type, bytes, characters, chunk count and digest |
| DELETE `/api/documents/{id}` | — | Developer/admin: removes the document and its chunks (audited) |
| POST `/api/knowledge/{id}/ingest` | `name`, `text`, optional `source`, `chunk_size`, `overlap` | New/replaced document, content digest |
| POST `/api/retrieve` | `knowledge_ids`, `query`, optional `top_k` | Retrieved citation records |
| POST `/api/answer` | `knowledge_ids`, `question`, optional `model`, `top_k` | Generation using supplied evidence, or refusal to invent absent evidence |
| POST `/api/guardrails/check` | `text` | Rule verdict and redacted text |

Knowledge objects optionally set `embedding_model` to a model of capability `embedding` (OpenAI-compatible or Ollama). Otherwise they use offline lexical retrieval. `rerank_model` (a chat model) reranks the top 20 candidates. Deleting a knowledge base deletes its documents.

## Runs

POST `/api/agents/{id}/run` body `{message, session?}`.

POST `/api/workflows/{id}/run` body `{text}`.

POST `/api/evaluations/{id}/run` body `{}`. An evaluation has `model`, `cases`, `pass_threshold`, optional `judge_model` and `knowledge_ids`. A case is `{input, contains?, excludes?, judge?: {criteria, min_score?}, grounded?}`. Results list each case with its `checks`, its judge and grounded verdicts (`score`, `reason`), and `passed`.

POST `/api/batches` body `{requests: [{model, messages, ...}]}`.

All return a durable job with HTTP 202. `Idempotency-Key` is supported and scoped to the tenant. Reusing a key with a different payload returns 409. Poll `GET /api/jobs/{id}`. States: queued, running, waiting_approval, waiting_external (a Zyntra handoff), completed, failed, rejected, interrupted.

POST `/api/approvals/{id}/decide`: `{decision: approved|rejected, digest}`. Requires different-person approver/admin. No replay, wrong fingerprint or expired approval allowed.

POST `/api/evaluations/compare`: `{baseline: job_id, candidate: job_id}`. Requires two completed evaluation jobs with identical cases. Returns score difference and release verdict.

## Prompt, recipe, governance

POST `/api/prompts/{id}/render` body `{variables: {key: value}}`.

POST `/api/recipes/{id}/export` returns a `TrainingRecipe` configuration. No training runs.

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

External action results are size limited and guardrail checked. POST failures are not retried automatically because a timeout may hide a committed change. Always inspect the destination system before a new run.
