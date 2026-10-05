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
| Ollama native completion | Adapter + local HTTP test | No native Ollama tool-call path; use its OpenAI endpoint for agents |
| AWS provider (Converse / ConverseStream) | Adapter + mocked client test | Optional boto3; AWS account, model access and region required; no tool calling |
| Model hosting and GPU scheduling | Roadmap/integration | Provided externally by Fabric/Gryvia; no model binaries launched by NUVORA |
| Document upload and extraction | Local test | txt, md, csv, json, html, docx (stdlib) and pdf (pypdf extra) up to 20 MB; no OCR, no crawling, no connector sync |
| Hybrid lexical retrieval | Local test | BM25 fused with hashed lexical vectors, stopwords and light stemming; recall@1 fixture gate in CI; vectors are not semantic embeddings |
| External semantic embeddings | Adapter + local HTTP test | OpenAI-compatible and Ollama `/api/embed`; no live embedding-model quality benchmark |
| LLM rerank | Local test | Optional chat-model rerank of the top 20; falls back to fused order on bad output |
| Retrieved citations | Local test | Source, document id, chunk, byte-position-as-Python-character-offset, SHA-256; retrieved evidence is not proof of answer correctness |
| Document-level ACL / entity resolution | Roadmap | Isolation is currently at tenant and knowledge-base selection level |
| Knowledge deletion | Local test | Delete one document (audited) or a knowledge base with all its documents |
| Enterprise connectors/actions | Local test + adapter | Admin-registered GET/POST tools with scalar schemas; POST requires separate-human approval; remote service behavior unverified |
| Tool-using agents | Local test | One call per model step, 1–20 steps, internal tools, Netra/Keep integration tools when configured, and admin-registered enterprise actions; no shell or unrestricted HTTP |
| Netra read tools | Local test (stub) | Status, incidents, flow summary, drop explanation; GET only; guardrail-screened; live Netra not exercised |
| Zyntra handoff | Local test (stub) | Workflow step creates a proposal, waits as `waiting_external`, polls every 5 s, resumes on approval, stops on rejection, fails on timeout; live Zyntra not exercised |
| Agent memory | Local test | User/session-scoped SQLite objects; writes require exact approval; no semantic memory retrieval |
| Code execution (Keep) | Local test (stub) | `run_code` (python/bash) only after a different person approves the exact code; sandbox without network, 60 s run, always deleted; no browser tools; live Keep not exercised |
| Durable jobs | Local test | One worker per replica; PostgreSQL claims jobs with `SKIP LOCKED`; queued jobs survive restart; running jobs of a dead worker become interrupted for review |
| Workflow branching/checkpoints | Local test | Topologically ordered steps; conditional execution; no arbitrary code nodes |
| Exact-action approvals | Local test | Different person, role check, fingerprint, one-hour expiry, no replay |
| Prompt revisions | Local test | Current editable prompt and immutable version snapshots in application storage |
| Deterministic guardrails | Local test | Regex/topic checks, not a classifier; no formal automated reasoning |
| Inference budget/concurrency | Local test | Chat tokens and estimated configured cost; four calls per user; embeddings excluded |
| Prompt/result cache | Local test | Opt-in, temperature zero, tenant/model/policy fingerprint, five-minute TTL; tools never cached |
| Batch requests | Local test | Up to 100 items; per-item failure; no AWS-style batch discount |
| SSE transport | Local test + adapter | `/api/chat/stream` and `/v1/chat/completions` (`stream=true`, OpenAI chunk frames) stream OpenAI-compatible, Ollama and AWS output as it arrives, released at sentence boundaries after guardrail checks; closing the client stops the upstream read |
| Evaluation / regression gate | Local test | Assertions, LLM-judge criteria and groundedness per case, with reasons; malformed judge output scores 0; no human review queue or production release integration |
| LoRA/QLoRA/distillation/quantization | Recipe | Export only; no training job submitted or model modified |
| Multimodal data automation | Roadmap | Workflow extract node projects fields from JSON; OCR/audio/video not implemented |
| MCP subset | Local test | Initialize/tools/list/tools/call over POST; no streaming MCP sessions or full protocol conformance claim |
| Hash-chained audit | Local test | Tamper detection within export; unsigned and rewriteable by a host administrator |
| Docker and Helm deployment | Local test | Built and deployed to a single-node k3s host with `scripts/deploy-remote.sh`; Helm renders PostgreSQL + replicas and refuses unsafe combinations; multi-node and ingress not exercised |
| PostgreSQL backend | Local test (PostgreSQL 14/16) | Full test suite runs on PostgreSQL in CI; schema_version, advisory-locked audit, shared throttle, SQLite migration script |
| Console | Local test | 19 pages, command palette, streaming playground, document upload, evaluation case editor and per-case results, SSO sign-in, integrations settings, resource drawers with history and diff, workflow builder with handoffs, run inspector, charts; Playwright smoke at 1440px and 390px in light and dark |
| Browser accessibility | Partial | Labelled controls, keyboard navigation and ARIA roles checked by tests; no formal audit with assistive technology |
| Multi-region HA / managed service SLAs | Roadmap | Several replicas on one PostgreSQL work; no multi-region, failover testing or SLA |

No market-superiority or AWS compliance equivalence claim is supported by these tests.
