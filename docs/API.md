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
| POST `/v1/embeddings` | OpenAI-style `model` (an enabled `embedding` model id), `input` (a string, or 1–128 strings of at most 20,000 characters, 400,000 in total), optional `encoding_format` (`float`, default, or `base64` little-endian float32) | `{object:"list", data:[{object:"embedding", index, embedding}], model, usage:{prompt_tokens,total_tokens}, nuvora:{evidence_class, cost, usage_estimated}}`. Developer/admin. Input passes the input guardrail (PII is redacted or the request refused with 422), the daily token budget (429) and the per-user concurrency limit; usage and an `embedding.completed` audit event are recorded. Providers report no embedding usage here, so tokens are estimated at 4 characters each. `dimensions` is refused (422). Providers: OpenAI-compatible, Ollama, and the offline demo (deterministic 64-dimension hashed vectors, not semantic) |
| POST `/api/chat/stream` | Same as `/api/chat` | `text/event-stream`: one `start` (model, routing, cached), `delta` events with guardrail-checked text released at sentence boundaries, then `done` (usage, cost, latency, evidence class) or `error` (`{error}`) |
| GET `/v1/models` | — | OpenAI-shaped model list, including routers as `router:<id>` |
| POST `/api/images` | `prompt`, optional `model`, `n` (1–4), `size` | Images from a model with the `image` capability, stored as expiring artifacts (`NUVORA_ARTIFACT_TTL_DAYS`, default 7). Guardrails and the daily budget apply |
| POST `/v1/images/generations` | OpenAI-style `prompt`, `model`, `n`, `size`, `response_format` | `{data: [{b64_json}]}` or `[{url}]` |
| GET `/api/artifacts/{id}` | — | The artifact bytes. Owner or administrator only |
| POST `/v1/chat/completions` | OpenAI-style model/messages, plus the options below | Chat envelope. With `stream=true`, live OpenAI `chat.completion.chunk` frames ending in `data: [DONE]`. Validation errors before the first byte are normal HTTP errors |
| POST `/api/knowledge/{id}/upload` | `name`, `content_type`, `content_base64`, optional `metadata`, `groups` | Extracts text from txt, md, csv, json, html, docx or pdf (≤ 20 MB). Images go through OCR and audio through transcription (the knowledge base's `ocr_model` / `transcription_model`, or the `ocr` extra for local OCR); scanned PDFs fall back to OCR. The document records its `extraction` method. Errors: 413 too large, 415 unknown type, 422 unreadable, 503 extra or model missing |
| GET `/api/knowledge/{id}/documents` | query `maxResults`, `nextToken` | Documents with content type, bytes, characters, chunk count and digest. See Pagination below |
| POST `/api/knowledge/{id}/ingestion-jobs` | `source`: `text` (`name`, `text`, optional `metadata`, `groups`), `documents` (1–100 items, each `text` or `content_base64` + `content_type`, with the `ingest`/`upload` fields) or `connector` (`connector_id`, admin; the connector must feed this knowledge base). Optional `description`, `clientToken` (or `Idempotency-Key`) | Developer/admin. 202 with the job: `id`, `knowledge_id`, `status`, `statistics`, `failure_reasons`, `created`, `started`, `finished`, `updated`. 409 while another ingestion job of this knowledge base is queued or running. The work reuses `ingest`, `upload` and connector sync, so guardrails, groups, metadata and audit behave the same |
| GET `/api/knowledge/{id}/ingestion-jobs` | `maxResults`, `nextToken` | Ingestion jobs of the knowledge base, newest first |
| GET `/api/knowledge/{id}/ingestion-jobs/{jobId}` | — | One job. `status` is `STARTING` (queued), `IN_PROGRESS`, `COMPLETE` or `FAILED` (failed, or interrupted by a restart). `statistics`: `documents_scanned`, `documents_new`, `documents_modified`, `documents_unchanged`, `documents_deleted`, `documents_failed`. A job is `FAILED` when every document failed; otherwise per-document problems are in `failure_reasons` (at most 50) and the job is `COMPLETE` |
| DELETE `/api/documents/{id}` | — | Developer/admin: removes the document and its chunks (audited) |
| POST `/api/knowledge/{id}/ingest` | `name`, `text`, optional `source`, `chunk_size`, `overlap`, `metadata`, `groups` | New/replaced document, content digest |
| POST `/api/retrieve` | `knowledge_ids`, `query`, optional `top_k`, `filter` | Retrieved citation records the caller may see. `filter` matches document metadata, every key must match: `{key: value}` or `{key: {in: [values]}}` (at most 10 keys) |
| POST `/api/answer` | `knowledge_ids`, `question`, optional `model`, `top_k`, `filter` | Generation using supplied evidence, or refusal to invent absent evidence. Includes a `grounding` score when the policy sets a grounding threshold |
| POST `/api/guardrails` (also GET list/one, DELETE `/api/guardrails/{id}`) | `name`, optional `description`, `input` and `output` sections, `blocked_input_message`, `blocked_output_message`; edit by POSTing to `/api/guardrails/{id}` with `expected_revision` | Guardrail resource whose current content is the working copy, **DRAFT**. Administrator writes; any role reads. Each section takes `blocked_topics`, `word_filters`, `regex_filters`, `pii_entities` (`mask`/`block`), `detect_injection` (input only), `max_chars`, `grounding_threshold`, `classifier_model` + `classifier_categories` + `classifier_threshold` (the same semantics as the tenant policy), and `strengths`. Unlike the tenant policy, a missing `pii_entities` redacts nothing |
| POST `/api/guardrails/{id}/versions` | optional `description` | Administrator: snapshots the DRAFT as the next immutable version (1, 2, …; at most 200). 201 with the snapshot |
| GET `/api/guardrails/{id}/versions` · `/versions/{n}` · `/versions/DRAFT` | — | `{items}` of numbered versions, or one version / the DRAFT; 404 for an unknown number, 400 for a malformed one |
| POST `/api/guardrails/{id}/apply` | `source` (`INPUT`/`OUTPUT`), `content` (1–20 strings), optional `version` (`DRAFT` default, or a number), `sources` (≤ 20 strings, for grounding on OUTPUT) | Developer/admin. `{action: NONE\|GUARDRAIL_INTERVENED, guardrail:{id,version}, source, outputs, assessments}`. `outputs` is empty for `NONE`; one item with the blocked message when anything was blocked; the masked texts (input order) when content was only masked. `assessments[i]` = `{index, action: NONE\|BLOCKED\|ANONYMIZED, findings:[{policy, code, action, match}]}`; codes: `DENIED_TOPIC`, `BLOCKED_WORD`, `REGEX_BLOCKED`, `PII_BLOCKED`, `PII_ANONYMIZED`, `REGEX_ANONYMIZED`, `CONTENT_FILTER`, `PROMPT_ATTACK`, `GROUNDING`, `MAX_CHARS`. No usage block; a classifier model call is metered like any side call. Audited as `guardrails.intervened` when something intervened. Python entry point: `Platform.apply_guardrail(p, guardrail_id, version, source, texts, sources=None)` returns the same dict |
| POST `/api/guardrails/check` | `text`, optional `sources` (≤ 20 strings) | Policy verdict: word and regex filters, PII entities, injection, classifier, and contextual grounding against `sources` |
| POST `/api/extract` | `fields` (`{name: {type, description?}}`, 1–30), one of `document_id`, `text` or `image` (data URL), optional `model`, `min_confidence` (default 0.7), `review` | 202 job. Returns typed fields with confidence and the fields under `min_confidence`. With `review: true`, such a result waits in an `extraction_review` approval |
| POST `/api/datasets` | `name`, `content` (JSONL in chat, completion or prompts format), optional `dry_run` | Validates 10–100,000 records (≤ 20 MiB), guard-checks each one, and returns stats. 200 for a dry run, 201 when stored |
| POST `/api/actions/import-openapi` | `spec` (OpenAPI 3 JSON), optional `base_url` (else the first server URL), `operations` (operationIds) | Admin: creates one typed action per GET/POST operation with flat inputs |

**Knowledge base `status`** (computed on `GET /api/knowledge` and `/api/knowledge/{id}`, never stored): `UPDATING` while an ingestion job is queued or running, `FAILED` when the latest ingestion job failed, otherwise `ACTIVE`. Only ingestion jobs count; the synchronous `ingest`/`upload` endpoints and connector syncs outside a job do not change it.

**Pagination.** `GET /api/{collection}` (all collections), `/api/knowledge/{id}/documents`, `/api/knowledge/{id}/ingestion-jobs` and `POST /api/retrieve` accept `maxResults` (1–100; for retrieve, 1–`top_k`) and `nextToken` (query string for GET, body field for retrieve) and return `nextToken` when more remain. Without `maxResults` and `nextToken` the response is unpaginated, as before. Lists are ordered newest first by creation time with the id as tie-break, and the token is a keyset cursor on that order, so inserts and deletes between calls do not repeat or skip items. Retrieve pages are slices of the ranked top `top_k` result, and the token is bound to the knowledge ids, query, filter and `top_k` (a mismatch is 400); it re-runs the search, so a changed corpus between pages can shift the ranking. Malformed tokens and out-of-range `maxResults` are 400.

Chat options, accepted by `/api/chat`, `/api/chat/stream` and `/v1/chat/completions`. A bad value is 400. A value the model's provider cannot honour is 422 naming the parameter, never silently ignored; with a router every tier must support it.

| Option | Shape | Providers |
|---|---|---|
| `tools` | 1–64 `{type:"function", function:{name, description?, parameters?}}`; name `[A-Za-z0-9_-]{1,64}`, parameters ≤ 20,000 characters, no other keys (so no `strict`) | demo, openai, ollama (native `/api/chat`), aws (Converse `toolConfig`) |
| `tool_choice` | `auto`, `none`, `required`, or `{type:"function", function:{name}}` naming a supplied tool; needs `tools` | openai, demo: all forms. ollama, aws: `auto` and `none` (tools are not sent). aws also `required` (`any`) and a named tool; ollama refuses those (422) |
| `response_format` | `{type:"text"}`, `{type:"json_object"}`, `{type:"json_schema", json_schema:{name, schema, strict?}}` (schema ≤ 20,000 characters) | demo, openai, ollama (`format`: `json` or the schema). aws refuses (422). Nuvora does not validate the model's output against the schema |
| `top_p` | number above 0, at most 1 | all providers |
| `stop` | a string, or up to 4 strings of 1–100 characters | all providers (aws: `stopSequences`) |

Tool-use turns: an assistant message may carry `tool_calls` (its `content` may be `null`), and a `tool` message answers one by `tool_call_id`. Their arguments pass the input guardrail. Responses carry `tool_calls`: the `/v1` envelope sets `content` to `null` and `finish_reason` to `tool_calls` when the model returned only calls, and `/api/chat` returns `tool_calls` on the result. The output guardrail screens call arguments; a redaction or block is a 422. Nuvora never executes request-supplied tools: the caller runs them and sends the result back. Requests with `tools` are never cached.

Per-request guardrails: `/api/chat`, `/api/chat/stream`, `/v1/chat/completions`, `/api/answer` and agent runs (`POST /api/agents/{id}/run`) accept `guardrail: {id, version}` (`version` is required: `DRAFT` or a number). The INPUT section screens every message and tool-call argument; the OUTPUT section screens the answer (buffered or at streaming sentence boundaries) and tool-call arguments. A refusal is a 422 whose message is the guardrail's `blocked_input_message` / `blocked_output_message`, and the audit event `guardrail.blocked` names `guardrail: "<id>:<version>"`. An unknown id or version is 404, a malformed reference 400. With no `guardrail` the tenant's default policy applies exactly as before; with one, it replaces that policy's filters for the request (the tenant policy still supplies the daily token budget and cache TTL). Responses are cached per guardrail content.

`strengths` maps content filters to `NONE`, `LOW`, `MEDIUM` or `HIGH`. Content categories (`hate`, `violence`, `sexual`, `self_harm`, `misconduct`, `prompt_attack`) need a `classifier_model` (except `prompt_attack`, which also turns on the deterministic instruction-override detector on INPUT) and map to the classifier confidence needed to flag: HIGH 0.3, MEDIUM 0.5, LOW 0.8, NONE off. `grounding` maps to the minimum grounding score: HIGH 0.8, MEDIUM 0.6, LOW 0.4. These are Nuvora's own thresholds, not AWS's, and the engine is deterministic rules plus an optional model-based classifier.

Streaming tool calls: provider fragments are assembled first, so arguments do not stream token by token. `/v1` then sends one `delta.tool_calls` chunk with all calls (`index`, `id`, `function.name`, complete `function.arguments`) and a final chunk with `finish_reason:"tool_calls"`. `/api/chat/stream` sends a `tool_calls` event (`{calls}`) before `done`.

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

## Bedrock-compatible API (preview)

A front door that speaks the Amazon Bedrock wire format, so the AWS SDKs and CLI can talk to Nuvora with `endpoint_url` pointing at it. **Preview: authentication, framing, errors and routing, plus the bedrock-runtime inference operations and two model-listing operations.** Every other Bedrock operation Nuvora recognises answers `501 UnsupportedOperationException` naming the operation; anything unrecognised answers `404 UnknownOperationException`. Nothing is silently accepted or ignored.

| Operation | Request | Status |
|---|---|---|
| ListFoundationModels | GET `/foundation-models` (`byProvider`, `byOutputModality`, `byInferenceType`, `byCustomizationType`; other parameters are rejected with `ValidationException`) | Implemented from the tenant's enabled models (`modelSummaries`; `modelArn` is `arn:nuvora:bedrock:<region>::foundation-model/<id>`) |
| GetFoundationModel | GET `/foundation-models/{modelIdentifier}` | Implemented (`modelDetails`; id or `…:foundation-model/<id>` ARN; disabled or unknown = `ResourceNotFoundException`) |
| Converse | POST `/model/{modelId}/converse` | Implemented, see below |
| ConverseStream | POST `/model/{modelId}/converse-stream` | Implemented: `messageStart`, `contentBlockStart` (tool use only), `contentBlockDelta`, `contentBlockStop`, `messageStop`, `metadata` |
| InvokeModel | POST `/model/{modelId}/invoke` | Implemented for Nuvora/OpenAI-shaped chat, Anthropic-messages chat and embeddings bodies |
| InvokeModelWithResponseStream | POST `/model/{modelId}/invoke-with-response-stream` | Implemented for the two chat shapes (`chunk` events); embedding models answer `ValidationException` |
| CountTokens | POST `/model/{modelId}/count-tokens` | Implemented as an **estimate** (characters / 4), see below |
| ApplyGuardrail | POST `/guardrail/{guardrailIdentifier}/version/{guardrailVersion}/apply` | Implemented on Nuvora guardrail resources, see **Guardrails on the Bedrock surface** below |
| StartAsyncInvoke/Get/List, Retrieve, RetrieveAndGenerate, InvokeAgent, InvokeFlow, ListInferenceProfiles/GetInferenceProfile, control-plane guardrails/agents/knowledge bases/jobs/logging/tags | Recognised paths (see `nuvora/bedrock/router.py`) | 501 until later packages implement them |

**Model ids.** `modelId` is a Nuvora model id, `router:<router id>`, or an ARN whose resource is `foundation-model/<model id>` or `inference-profile/<router id>` (a router is the closest thing Nuvora has to an inference profile; `router:` inside the ARN is optional). `:` and `/` arrive percent-encoded and are decoded. An unknown model or router is `ResourceNotFoundException`; a disabled model, or one whose capability the operation cannot use (an embedding model on Converse), is `ValidationException`. Bedrock's own ids (`anthropic.claude-…`) are not aliases: register the model in Nuvora and use its id.

**Converse / ConverseStream** map onto the same pipeline as `/v1/chat/completions` (`Platform.chat` / `open_stream`): routing, tenant guardrails, daily budget, concurrency limit, usage ledger and audit apply identically, and the caller needs the developer or admin role (`AccessDeniedException` otherwise).
- Request: `messages` (roles user/assistant; content blocks `text`, `image` with `source.bytes` for png/jpeg/webp, `toolUse`, `toolResult` with `text`/`json` content), `system` (text blocks), `inferenceConfig` (`maxTokens` 1-8192, `temperature` 0-2, `topP`, `stopSequences` up to 4), `toolConfig` (`tools[].toolSpec`, `toolChoice` auto/any/tool). A `toolResult` becomes a tool message; `status: "error"` prefixes the text with `Tool error: ` because the internal form has no error flag. Images need a vision model (the offline demo accepts them).
- `guardrailConfig` (`guardrailIdentifier`, `guardrailVersion`, `trace`, and on ConverseStream `streamProcessingMode`) selects a Nuvora guardrail, see below. Refused by name with `ValidationException`, never ignored: `additionalModelRequestFields`, `additionalModelResponseFieldPaths`, `promptVariables`, `requestMetadata`, `performanceConfig`, `serviceTier`, and the blocks `document`, `video`, `guardContent`, `reasoningContent`, `cachePoint`, `citationsContent`, `searchResult`, `toolUse` on a user message, `gif` images, `s3Location` sources, `systemTool`, `toolSpec.strict`.
- Response: `output.message.content[]` (`text`, `toolUse`), `stopReason`, `usage{inputTokens,outputTokens,totalTokens}`, `metrics.latencyMs`, header `X-Nuvora-Evidence-Class` (`synthetic` for the offline demo). Providers do not report why generation ended, so `stopReason` is derived: `tool_use` when tool calls came back, `max_tokens` when the completion used the whole `maxTokens`, otherwise `end_turn`. `stop_sequence` and `content_filtered` are never returned. When a guardrail blocks the input or the output, Converse answers **200** with `stopReason: guardrail_intervened`, the guardrail's blocked message (a fixed explanatory text for the tenant policy) and zero usage (the block is audited as `guardrail.blocked`; a refused output is not recorded in the usage ledger, as for native chat).
- Streaming: tool calls are released whole after the output guardrail has checked their arguments (one `contentBlockStart`/`Delta`/`Stop` per call), and text is released at sentence boundaries after the guardrail, as for `/api/chat/stream`. Failures before the first frame are normal HTTP errors; later ones are exception frames named `internalServerException`, `modelStreamErrorException`, `validationException`, `throttlingException` or `serviceUnavailableException`.

**Error mapping:** guardrail 422 -> `guardrail_intervened` (Converse) or `ValidationException` (Invoke\*); other 422/400/409 -> `ValidationException`; 403 -> `AccessDeniedException`; 404 -> `ResourceNotFoundException`; 429 (budget, concurrency) -> `ThrottlingException`; 502 provider failure -> `ModelErrorException` (424); 503 -> `ServiceUnavailableException`.

**InvokeModel / InvokeModelWithResponseStream** take the model's native body as JSON (`contentType` and `accept` must be `application/json`; `guardrailIdentifier`, `guardrailVersion` and `trace` select a guardrail, see below; `performanceConfigLatency` is refused). The body shape is picked by the request:
- *Nuvora/OpenAI chat* (default): `messages`, `max_tokens`, `temperature`, `top_p`, `stop`, `tools`, `tool_choice`, `response_format`. Returns the `chat.completion` object `/v1/chat/completions` returns; streams `chat.completion.chunk` objects (final chunk carries `finish_reason` and `usage`).
- *Anthropic messages* (when `anthropic_version` is present; must be `bedrock-2023-05-31`): `max_tokens` (required), `messages` (string content, or `text`/`image` base64/`tool_use`/`tool_result` blocks), `system` (string or text blocks), `temperature`, `top_p`, `stop_sequences`, `tools[{name,description,input_schema}]`, `tool_choice` (`auto|any|none|tool`). Returns `{id,type:"message",role,model,content[],stop_reason,stop_sequence:null,usage{input_tokens,output_tokens}}`; streams `message_start`, `content_block_start/delta/stop`, `message_delta`, `message_stop` (with `amazon-bedrock-invocationMetrics`). `top_k`, `metadata`, `thinking`, `stream` and any other field are refused by name. Only the *shape* is Anthropic's; the model behind it is whatever the Nuvora model id points to.
- *Embeddings* (embedding models): Nuvora/OpenAI `{"input": str|[str], "encoding_format"}` returns the `/v1/embeddings` object; Titan-style `{"inputText": str}` returns `{"embedding": [...], "inputTextTokenCount": n}`. `dimensions`, `normalize`, `embeddingTypes` and Cohere/other shapes are refused (the model decides the vector size).
- Responses carry `X-Amzn-Bedrock-Input-Token-Count`, `X-Amzn-Bedrock-Output-Token-Count`, `X-Amzn-Bedrock-Invocation-Latency` and `X-Nuvora-Evidence-Class`.

**Guardrails on the Bedrock surface.** The identifier is a Nuvora guardrail id (or an ARN ending `guardrail/<id>`) and the version is `DRAFT` or a version number, as in `/api/guardrails`. Unknown id or version is `ResourceNotFoundException`; a malformed version is `ValidationException`. The guardrail is applied by the same `guardrail: {id, version}` request reference as native chat (its INPUT section over every message, its OUTPUT section over the answer and tool arguments; nothing from the tenant policy is applied alongside it).
- *Converse / ConverseStream* `guardrailConfig`: an intervention is `stopReason: guardrail_intervened` with the input or output blocked message as the assistant text. `trace: enabled|enabled_full` adds `trace.guardrail` (`metadata.trace.guardrail` on streams) with `inputAssessment` (the same mapping as ApplyGuardrail, re-evaluated from the request text, so a classifier is called again) or, when the model output was blocked, `outputAssessments: {id: []}` and an `actionReason` saying the blocked output is not retained (no `modelOutput`, no per-policy detail). No trace is returned when nothing was blocked, and `enabled_full` adds nothing beyond `enabled` for these traces. Masking (anonymised PII) happens silently and does not change `stopReason`. `streamProcessingMode: async` is accepted but processed as `sync`: text is always released after the output guardrail. A trace without an intervention, and `guardContent` blocks, are not supported.
- *InvokeModel / InvokeModelWithResponseStream*: the `guardrailIdentifier`/`guardrailVersion` parameters (headers `X-Amzn-Bedrock-GuardrailIdentifier`/`-Version`, sent together) behave as above. The body gains `amazon-bedrock-guardrailAction` (`NONE` or `INTERVENED`; on streams, in the last chunk); an intervened chat body holds the blocked message, and `trace` (`X-Amzn-Bedrock-Trace`) adds `amazon-bedrock-trace.guardrail`. A trace header without a guardrail, or a guardrail on an embedding model, is `ValidationException`. Without an explicit guardrail the tenant policy still answers an invoke refusal as `ValidationException`.
- *ApplyGuardrail* body: `source` `INPUT|OUTPUT`, `content[].text{text, qualifiers}`, `outputScope` `INTERVENTIONS|FULL`. Qualifiers: `grounding_source` texts are not guarded and become the sources for contextual grounding (OUTPUT only); `guard_content` and unqualified texts are guarded (at most 20); `query` is refused (no relevance check) and so are `image` blocks and combined qualifiers. Response: `action`, `outputs` (empty when nothing intervened; the blocked message when blocked; the masked texts when only anonymised), `assessments` (one merged assessment for all guarded texts), `usage`, `guardrailCoverage`, and `actionReason` on an intervention. Requires the developer or admin role, audits `guardrails.intervened`.
- *Mapping of Nuvora findings to assessments*: denied topic -> `topicPolicy.topics` (`DENY`); blocked word -> `wordPolicy.customWords` (`managedWordLists` is always empty); PII block/mask -> `sensitiveInformationPolicy.piiEntities` (`email` EMAIL, `card` CREDIT_DEBIT_CARD_NUMBER, `ssn` US_SOCIAL_SECURITY_NUMBER, `ipv4` IP_ADDRESS, `phone` PHONE, `iban` INTERNATIONAL_BANK_ACCOUNT_NUMBER; `match` is the matched text, recomputed from the request); regex filter -> `regexes` (name, pattern, first match); classifier categories hate, violence, sexual, misconduct and the prompt-attack detector -> `contentPolicy.filters` (`filterStrength` is the configured strength; `confidence` is the lowest bucket the threshold guarantees, HIGH strength = LOW confidence, because the classifier's own score is not carried; the deterministic prompt-attack match reports `HIGH`); grounding -> `contextualGroundingPolicy.filters` (`GROUNDING`, with the threshold and a recomputed score; `RELEVANCE` is never produced). **Cannot be mapped**: the `self_harm` filter (Bedrock has no such type; `INSULTS` is never produced either), `max_chars` size blocks and image content. They still make `action` `GUARDRAIL_INTERVENED` and are named in `actionReason`. Every assessment also carries a non-standard `nuvora.findings` array with Nuvora's own codes (SDKs drop it). `outputScope: FULL` also lists configured but undetected topics, words, PII types, regex filters, content filters (`confidence: NONE`) and, given sources, grounding, with `detected: false`.
- *Usage*: `usage` counts text units the way Bedrock defines them (1 unit = 1000 characters, rounded up, per policy type the guardrail configures; regexes count as `sensitiveInformationPolicyFreeUnits`; image and automated-reasoning units are 0). Nuvora does not bill them: the response header `X-Nuvora-Guardrail-Units` says so. `invocationMetrics.guardrailProcessingLatency` is measured in milliseconds.

**CountTokens** takes `input.converse` (same fields as Converse) or `input.invokeModel.body` (base64 of an Invoke body) and returns `{"inputTokens": n}`. The number is an **estimate** (message and tool-definition characters / 4, plus a flat 1000 characters-equivalent per image), not the model's tokenizer; the response header `X-Nuvora-Token-Count: estimate; characters/4` says so. It does not call a model, so it records no usage and consumes no budget, but it still requires the developer or admin role.

Paths root at `/model/…`, `/guardrail/…`, `/foundation-models`, `/inference-profiles`, `/guardrails`, `/agents`, `/knowledgebases`, `/flows`, `/retrieveAndGenerate` and similar. Requests are routed by method and path; the SigV4 credential-scope service (`bedrock`, `bedrock-runtime`, `bedrock-agent`, `bedrock-agent-runtime`) must be one of those four but does not select the route, because SDKs sign several of these services as `bedrock`. Any region is accepted. The console's own `/agents`, `/guardrails` and `/knowledgebases` pages are untouched unless the request carries an AWS4 or Bearer `Authorization` header.

**Authentication**
- AWS Signature V4 (header form) with an access key from `/api/aws-credentials`. Verified: canonical request (path encoded twice, sorted query, trimmed headers), string to sign, signing key, constant-time compare, ±5 minute clock skew, payload hash (`x-amz-content-sha256` must match the body, or be `UNSIGNED-PAYLOAD`), `host` and `x-amz-date` must be signed. Not supported: presigned query-string URLs, `STREAMING-*` chunk signing, `X-Amz-Security-Token` session credentials. Chunked request bodies are refused.
- `Authorization: Bearer <Nuvora token>` (a session or service token, or an OIDC JWT): what the SDKs send for `AWS_BEARER_TOKEN_BEDROCK`.
- Both resolve to the same principal as the native API (tenant, user, role, groups). A credential never outranks its user's current role, and is deleted with the user.
- Failures: `403 MissingAuthenticationTokenException | UnrecognizedClientException | InvalidSignatureException | IncompleteSignatureException`. Twenty failures in five minutes from one client address answer `429 ThrottlingException`. Failures against a known access key id add a `bedrock.auth.failed` audit event (reason, service, client address, never the secret or signature); unknown key ids are only throttled.

**Errors** are JSON `{"message": "..."}` with `x-amzn-ErrorType` and `x-amzn-RequestId` headers: ValidationException 400, AccessDeniedException 403, ResourceNotFoundException 404, ConflictException 409, ThrottlingException 429, InternalServerException 500, ServiceUnavailableException 503, plus the gateway errors above. Native `Fault`s raised inside an operation map by status.

**Streams** use `application/vnd.amazon.eventstream` (`nuvora/bedrock/eventstream.py` encodes and decodes frames with both CRC32s and string/byte-array/integer/uuid headers). The connection closes at the end of the stream; a failure after the first frame is sent as an exception frame.

**Credential administration** (admin; needs `NUVORA_SECRET_KEY`, see Operations):
- POST `/api/aws-credentials` `{role?: viewer|developer, lifetime?: 60..31536000 seconds (default 30 days), label?, username?}` returns `{access_key_id, secret_access_key, username, role, label, created, expires}` with HTTP 201. The secret is shown once. `username` issues for another member; the role cannot exceed that member's role. Without `NUVORA_SECRET_KEY` (32+ characters) the call answers 503.
- GET `/api/aws-credentials` lists live credentials without secrets. DELETE `/api/aws-credentials/{access_key_id}` revokes.

```bash
export AWS_ACCESS_KEY_ID=NVRA… AWS_SECRET_ACCESS_KEY=… AWS_DEFAULT_REGION=us-east-1
aws bedrock list-foundation-models --endpoint-url http://127.0.0.1:8789
aws bedrock-runtime converse --endpoint-url http://127.0.0.1:8789 --model-id <nuvora model id> \
  --messages '[{"role":"user","content":[{"text":"Hello"}]}]'
```

The `aws` CLI one-liner above is the intended usage and has not been run for this package: it is verified through boto3/botocore (the same request builders and parsers), not the CLI itself.

## Failure conventions

400 validation, 401 authentication, 403 role/origin/tool/host denial, 404 missing tenant object, 409 stale/expired/reused state, 413 oversized body, 422 guardrail or model capability refusal, 429 budget/concurrency throttle, 502 provider failure, 503 unavailable optional adapter. Some optimistic storage conflicts currently return 400.

Provider errors are sanitized so provider bodies or credentials do not become client errors.

## Enterprise action registry

An action object has `name`, `url`, `method` (`GET` or `POST`), optional `description` and `key_env`, and `input_schema` (object with scalar typed properties). Registering or editing one requires admin. POST actions always require approval; GET relies on the operator's assertion that the endpoint is read-only. Select agent tools named `action_<id>`, or create a workflow action step `{id, type: action, action_id, arguments}`. Arguments are pinned in the approved action. Never use GET endpoints that cause writes.

`/api/actions/import-openapi` creates these from an OpenAPI 3 document.

An `mcp_servers` object (admin) points at a remote MCP server's `url`, with an optional `key_env` and `readonly` flag. Its tools appear to agents as `mcp_<first 8 characters of the server id>_<tool>`. Calls to a server that is not `readonly` are staged as approvals, like POST actions.

External action results are size limited and guardrail checked. POST failures are not retried automatically because a timeout may hide a committed change. Always inspect the destination system before a new run.
