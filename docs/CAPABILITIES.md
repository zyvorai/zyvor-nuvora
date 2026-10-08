# Capability matrix

Evidence terms: **local test** means exercised in this repository; **adapter** means implementation exists but a live external service was not exercised; **recipe** means configuration export, not execution; **roadmap** means absent.

| Capability | Status | Practical boundary |
|---|---|---|
| Password sign-in and HttpOnly sessions | Local test | PBKDF2-SHA256, 8-hour sessions, failed-login throttling stored in the database (shared across replicas) |
| OIDC single sign-on | Local test (fake IdP) | Code flow + PKCE, ID token claim checks, JIT users with role sync from groups, bearer JWT verification via JWKS (RS/PS/ES); one provider; no SAML, SCIM or back-channel logout; not exercised against a live Keycloak/Entra |
| Tenant storage and RBAC | Local test | Object reads/writes bind to the authenticated tenant; admin is tenant-local |
| Service tokens | Local test | Only viewer/developer roles; no approval authority; hash stored at rest; listed and revoked by owner or admin; revoked when the owner is demoted below developer |
| Password change and member management | Local test | Password change revokes your other sessions; admins change roles or remove members; you can't change yourself and the last admin is protected |
| OpenAI-compatible completion | Adapter + local HTTP test | Buffered or live-streamed; mapped usage; Fabric/Gryvia presets and `/v1/models` discovery; live Fabric/Gryvia endpoints not exercised |
| Ollama native completion | Adapter + local HTTP test + live (CPU) | Exercised live with qwen2.5 and granite3.2-vision by `scripts/e2e-live.py`; no native Ollama tool-call path, so use its OpenAI endpoint for agents |
| AWS provider (Converse / ConverseStream) | Adapter + mocked client test | Optional boto3; AWS account, model access and region required; no tool calling |
| Bedrock-shaped wire API (preview) | Local test + botocore client (when installed) | SigV4 header authentication with issued access keys, bearer tokens, `application/vnd.amazon.eventstream` framing, Bedrock error shape and routing; only ListFoundationModels is implemented, every other recognised operation returns 501. Tested against AWS's published SigV4 vectors and the AWS SDK for Python against a local server; no AWS account or live Bedrock endpoint exercised, no AWS compliance or behavioural equivalence claim |
| Cascade routers | Local test | 2–5 chat models tried cheapest first; escalate on empty answer, unsure phrasing or judge score below `min_score`; tool-call answers accepted at once; `router:<id>` in console and `/v1`; no latency-aware or learned routing |
| Image generation | Adapter + local HTTP test | OpenAI-compatible `b64_json` image endpoints and a synthetic demo; five sizes, up to 4 images; artifacts expire after `NUVORA_ARTIFACT_TTL_DAYS`; no editing or variations; live image models not exercised |
| Model hosting and GPU scheduling | Roadmap/integration | Provided externally by Fabric/Gryvia or your trainer; no model binaries launched by Nuvora |
| Document upload and extraction | Local test | txt, md, csv, json, html, docx (stdlib) and pdf (pypdf extra) up to 20 MB; images and scanned PDFs via a vision model or the `ocr` extra (Tesseract); audio via a transcription model; no video |
| Knowledge base ingestion jobs | Local test | `POST /api/knowledge/{id}/ingestion-jobs` runs text, documents or a connector sync as a background job with `STARTING`/`IN_PROGRESS`/`COMPLETE`/`FAILED`, new/modified/unchanged/deleted/failed statistics and failure reasons; one running job per knowledge base; computed knowledge base `status`; `maxResults`/`nextToken` pagination on collection lists, documents, ingestion jobs and retrieve. Modelled on Bedrock's shape, not AWS wire-compatible; no live S3/Confluence run; PostgreSQL leg not run (no schema change) |
| Knowledge connectors | Local test (stub servers) | Web crawler (robots.txt, depth and page limits), S3 prefix, Confluence space; incremental sync by content digest, removing deleted pages; 15 minutes to 7 days between syncs; hosts limited to `NUVORA_CONNECTOR_HOSTS`; live S3/Confluence not exercised |
| Structured extraction | Local test | `/api/extract` and workflow extract steps fill typed fields (string, number, integer, boolean, date) with confidence; with `review` set, results below `min_confidence` wait for approval; bare values from small models are kept at confidence 0 |
| Hybrid lexical retrieval | Local test | BM25 fused with hashed lexical vectors, stopwords and light stemming; recall@1 fixture gate in CI; vectors are not semantic embeddings |
| External semantic embeddings | Adapter + local HTTP test + live (CPU) | OpenAI-compatible and Ollama `/api/embed`; nomic-embed-text exercised live; no embedding-model quality benchmark |
| LLM rerank | Local test | Optional chat-model rerank of the top 20; falls back to fused order on bad output |
| Retrieved citations | Local test | Source, document id, chunk, byte-position-as-Python-character-offset, SHA-256; retrieved evidence is not proof of answer correctness |
| Document-level ACL | Local test | Documents carry metadata (filters with equality or `in`, up to 10 keys) and user groups; retrieval drops documents outside the caller's groups; no entity resolution or per-chunk ACL |
| Knowledge deletion | Local test | Delete one document (audited) or a knowledge base with all its documents |
| Enterprise actions | Local test + adapter | Admin-registered GET/POST tools with scalar schemas, or imported from an OpenAPI 3 document; POST requires separate-human approval; remote service behavior unverified |
| Tool-using agents | Local test | One call per model step, 1–20 steps, internal tools, Netra/Keep integration tools when configured, and admin-registered enterprise actions; no shell or unrestricted HTTP |
| Netra read tools | Local test (stub) | Status, incidents, flow summary, drop explanation; GET only; guardrail-screened; live Netra not exercised |
| Zyntra handoff | Local test (stub) | Workflow step creates a proposal, waits as `waiting_external`, polls every 5 s, resumes on approval, stops on rejection, fails on timeout; live Zyntra not exercised |
| Agent memory | Local test | Session memory plus long-term memory search per user; writes and session summaries require exact approval; lexical, not semantic, search |
| Code execution (Keep) | Local test (stub) | `run_code` (python/bash) only after a different person approves the exact code; sandbox without network, 60 s run, always deleted; no browser tools; live Keep not exercised |
| Durable jobs | Local test | One worker per replica; PostgreSQL claims jobs with `SKIP LOCKED`; queued jobs survive restart; running jobs of a dead worker become interrupted for review |
| Workflow branching/checkpoints | Local test | Topologically ordered steps; conditional execution; no arbitrary code nodes |
| Exact-action approvals | Local test | Different person, role check, fingerprint, one-hour expiry, no replay |
| Prompt revisions and experiments | Local test | Editable prompt with immutable snapshots; weighted variants with sticky per-subject rendering; experiments score each variant on an evaluation suite; no online traffic splitting outside Nuvora |
| Guardrails | Local test + adapter | Word and regex filters, PII entities with checksums (IBAN mod-97, card Luhn) masked or blocked, lexical grounding score, optional classifier model that fails closed; classifier quality depends on your model; no formal automated reasoning |
| Inference budget/concurrency | Local test | Chat tokens and estimated configured cost; four calls per user; embeddings excluded |
| Prompt/result cache | Local test | Opt-in, temperature zero, tenant/model/policy fingerprint, TTL 30 s–24 h per policy (default five minutes); tools never cached; provider cached-token pricing tracked separately |
| Batch requests | Local test | Up to 100 items; per-item failure; no AWS-style batch discount |
| SSE transport | Local test + adapter | `/api/chat/stream` and `/v1/chat/completions` (`stream=true`, OpenAI chunk frames) stream OpenAI-compatible, Ollama and AWS output as it arrives, released at sentence boundaries after guardrail checks; closing the client stops the upstream read |
| Evaluation / regression gate | Local test | Assertions, LLM-judge criteria and groundedness per case, with reasons; malformed judge output scores 0; no human review queue or production release integration |
| LoRA/QLoRA/distillation | Adapter + local HTTP test (stub trainer) | Validated JSONL datasets; jobs submitted to `NUVORA_TRAINER_URL`, polled for up to 7 days, and the result registered as a model; no trainer bundled; quantization and evaluation recipes stay export-only |
| Multimodal chat | Adapter + local HTTP test | Image content parts on OpenAI-compatible, Ollama and AWS providers, up to 4 images of 7 MB; no audio or video in chat |
| MCP | Local test | Server: initialize/tools/list/tools/call over POST. Client: remote MCP servers registered by an admin, whose writing tools wait for approval; no streaming MCP sessions or full protocol conformance claim |
| Run tracing | Local test | Per-step timing in a run waterfall; optional OTLP/HTTP JSON export to `NUVORA_OTEL_ENDPOINT` |
| Hash-chained audit | Local test | Tamper detection within export; unsigned and rewriteable by a host administrator |
| Docker and Helm deployment | Local test | Built and deployed to a single-node k3s host with `scripts/deploy-remote.sh`; Helm renders PostgreSQL + replicas, extra `NUVORA_*` env and an `envFromSecret`, and refuses unsafe combinations; multi-node and ingress not exercised |
| PostgreSQL backend | Local test (PostgreSQL 14/16) | Full test suite runs on PostgreSQL in CI; schema_version, advisory-locked audit, shared throttle, SQLite migration script |
| Console | Local test | 22 pages, command palette, streaming playground with image mode, document upload, guardrail policy editor, routers, connectors, model studio, evaluation case editor and per-case results, SSO sign-in, integrations settings, resource drawers with history and diff, workflow builder, run inspector with waterfall, charts; Playwright smoke at 1440px and 390px in light and dark |
| Browser accessibility | Partial | Labelled controls, keyboard navigation and ARIA roles checked by tests; no formal audit with assistive technology |
| Multi-region HA / managed service SLAs | Roadmap | Several replicas on one PostgreSQL work; no multi-region, failover testing or SLA |

No market-superiority or AWS compliance equivalence claim is supported by these tests.
