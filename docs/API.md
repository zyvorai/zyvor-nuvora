# API reference

Prefix `/api`; inference compatibility prefix `/v1`. Responses are JSON. Body size is capped at 1 MiB. Browser sessions use HttpOnly cookies and `X-CSRF-Token`; automation uses bearer tokens.

## Authentication and roles

| Endpoint | Method | Result / permission |
|---|---|---|
| `/api/login` | POST | `{tenant, username, password}` → principal + CSRF; HttpOnly session cookie |
| `/api/session` | GET | Current principal and CSRF |
| `/api/logout` | POST | Revoke the current session/token |
| `/api/password` | POST | `{current, new}`; changes your password and revokes your other sessions |
| `/api/tokens` | POST | Admin/developer: `{role: viewer\|developer, lifetime: seconds, label?}`; token returned once |
| `/api/tokens` | GET | Active service tokens (id, owner, role, label, created, expires). Admins see the workspace; others see their own |
| `/api/tokens/{id}` | DELETE | Revoke a service token. Owner or administrator |
| `/api/users` | GET / POST | Tenant administrator lists/creates members |
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
| POST `/v1/chat/completions` | OpenAI-style model/messages | Chat envelope; optional buffered SSE when `stream=true` |
| POST `/api/knowledge/{id}/ingest` | `name`, `text`, optional `source`, `chunk_size`, `overlap` | New/replaced document, content digest |
| POST `/api/retrieve` | `knowledge_ids`, `query`, optional `top_k` | Retrieved citation records |
| POST `/api/answer` | `knowledge_ids`, `question`, optional `model`, `top_k` | Generation using supplied evidence, or refusal to invent absent evidence |
| POST `/api/guardrails/check` | `text` | Rule verdict and redacted text |

Knowledge objects optionally set `embedding_model` to a model of capability `embedding`. Otherwise they use offline lexical retrieval.

## Runs

POST `/api/agents/{id}/run` body `{message, session?}`.

POST `/api/workflows/{id}/run` body `{text}`.

POST `/api/evaluations/{id}/run` body `{}`.

POST `/api/batches` body `{requests: [{model, messages, ...}]}`.

All return a durable job with HTTP 202. `Idempotency-Key` is supported and scoped to the tenant. Reusing a key with a different payload returns 409. Poll `GET /api/jobs/{id}`. States: queued, running, waiting_approval, completed, failed, rejected, interrupted.

POST `/api/approvals/{id}/decide`: `{decision: approved|rejected, digest}`. Requires different-person approver/admin. No replay, wrong fingerprint or expired approval allowed.

POST `/api/evaluations/compare`: `{baseline: job_id, candidate: job_id}`. Requires two completed evaluation jobs with identical cases. Returns score difference and release verdict.

## Prompt, recipe, governance

POST `/api/prompts/{id}/render` body `{variables: {key: value}}`.

POST `/api/recipes/{id}/export` returns a `TrainingRecipe` configuration. No training runs.

GET `/api/overview`, `/api/usage`, `/api/audit`, `/api/tools` provide workspace summary, inference ledger, audit verification and the registered internal tools.

`/api/audit` accepts `actor`, `action` (prefix, such as `approval.`) and `since` / `until` (Unix seconds). Verification always covers the whole chain, not just the filtered page.

GET `/api/usage/series?days=1..90` returns daily buckets (requests, tokens, cost, latency, cache hits), a per-model breakdown and today's budget. GET `/api/runs/stats` returns run counts by status and kind and median duration.

POST `/mcp` supports a small JSON-RPC tools subset: initialize, tools/list, tools/call. `list_models` and `search_knowledge` are read-only. It is not a full MCP streaming transport.

## Failure conventions

400 validation, 401 authentication, 403 role/origin/tool/host denial, 404 missing tenant object, 409 stale/expired/reused state, 413 oversized body, 422 guardrail or model capability refusal, 429 budget/concurrency throttle, 502 provider failure, 503 unavailable optional adapter. Some optimistic storage conflicts currently return 400.

Provider errors are sanitized so provider bodies or credentials do not become client errors.

## Enterprise action registry

An action object has `name`, `url`, `method` (`GET` or `POST`), optional `description` and `key_env`, and `input_schema` (object with scalar typed properties). Registering or editing one requires admin. POST actions always require approval; GET relies on the operator's assertion that the endpoint is read-only. Select agent tools named `action_<id>`, or create a workflow action step `{id, type: action, action_id, arguments}`. Arguments are pinned in the approved action. Never use GET endpoints that cause writes.

External action results are size limited and guardrail checked. POST failures are not retried automatically because a timeout may hide a committed change. Always inspect the destination system before a new run.
