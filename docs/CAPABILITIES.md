# Capability matrix

Evidence terms: **local test** means exercised in this repository; **adapter** means implementation exists but a live external service was not exercised; **recipe** means configuration export, not execution; **roadmap** means absent.

| Capability | Status | Practical boundary |
|---|---|---|
| Password sign-in and HttpOnly sessions | Local test | PBKDF2-SHA256, 8-hour sessions, process-local failed-login throttling |
| Tenant storage and RBAC | Local test | Object reads/writes bind to the authenticated tenant; admin is tenant-local |
| Service tokens | Local test | Only viewer/developer roles; no approval authority; hash stored at rest; listed and revoked by owner or admin; revoked when the owner is demoted below developer |
| Password change and member management | Local test | Password change revokes your other sessions; admins change roles or remove members; you can't change yourself and the last admin is protected |
| OpenAI-compatible completion | Adapter + local HTTP test | Buffered upstream; mapped usage; vLLM/Fabric/Gryvia require external endpoints |
| Ollama native completion | Adapter + local HTTP test | No native Ollama tool-call path; use its OpenAI endpoint for agents |
| Bedrock Converse | Adapter | Optional boto3; AWS account, model access and region required; no tool calling |
| Model hosting and GPU scheduling | Roadmap/integration | Provided externally by Fabric/Gryvia; no model binaries launched by NUVORA |
| Text ingestion and replacement | Local test | Plain text/Markdown/JSON content supplied by user; no crawling or binary parsing |
| Hybrid lexical retrieval | Local test | BM25 fused with hashed lexical vectors; vectors are not semantic embeddings |
| External semantic embeddings | Adapter + local HTTP test | OpenAI embeddings format only; no live embedding-model quality benchmark |
| Retrieved citations | Local test | Source, document id, chunk, byte-position-as-Python-character-offset, SHA-256; retrieved evidence is not proof of answer correctness |
| Document-level ACL / entity resolution | Roadmap | Isolation is currently at tenant and knowledge-base selection level |
| Knowledge deletion | Roadmap | Reingestion replaces a named document; API deletion of individual documents is not exposed |
| Enterprise connectors/actions | Local test + adapter | Admin-registered GET/POST tools with scalar schemas; POST requires separate-human approval; remote service behavior unverified |
| Tool-using agents | Local test | One call per model step, 1–20 steps, four internal tools plus admin-registered enterprise actions; no shell or unrestricted HTTP |
| Agent memory | Local test | User/session-scoped SQLite objects; writes require exact approval; no semantic memory retrieval |
| MicroVM/browser/code execution | Roadmap/integration | Keep is not invoked by this release; agents run inside the server process |
| Durable jobs | Local test | Single worker per server; queued jobs survive restart; running jobs become interrupted for review |
| Workflow branching/checkpoints | Local test | Topologically ordered steps; conditional execution; no arbitrary code nodes |
| Exact-action approvals | Local test | Different person, role check, fingerprint, one-hour expiry, no replay |
| Prompt revisions | Local test | Current editable prompt and immutable version snapshots in application storage |
| Deterministic guardrails | Local test | Regex/topic checks, not a classifier; no formal automated reasoning |
| Inference budget/concurrency | Local test | Chat tokens and estimated configured cost; four calls per user; embeddings excluded |
| Prompt/result cache | Local test | Opt-in, temperature zero, tenant/model/policy fingerprint, five-minute TTL; tools never cached |
| Batch requests | Local test | Up to 100 items; per-item failure; no AWS-style batch discount |
| SSE transport | Local test + adapter | `/api/chat/stream` streams OpenAI-compatible and Ollama output as it arrives, released at sentence boundaries after guardrail checks; demo and Bedrock replay a complete answer; `/v1/chat/completions` with `stream=true` stays buffered; closing the client stops the upstream read |
| Evaluation / regression gate | Local test | Deterministic textual assertions; no human/LLM judges or production release integration |
| LoRA/QLoRA/distillation/quantization | Recipe | Export only; no training job submitted or model modified |
| Multimodal data automation | Roadmap | Workflow extract node projects fields from JSON; OCR/audio/video not implemented |
| MCP subset | Local test | Initialize/tools/list/tools/call over POST; no streaming MCP sessions or full protocol conformance claim |
| Hash-chained audit | Local test | Tamper detection within export; unsigned and rewriteable by a host administrator |
| Docker and Helm deployment | Local test | Built and deployed to a single-node k3s host with `scripts/deploy-remote.sh`; multi-node and ingress not exercised |
| Console | Local test | 19 pages, command palette, streaming playground, resource drawers with history and diff, workflow builder, run inspector, charts, API keys and Settings; Playwright smoke at 1440px and 390px in light and dark |
| Browser accessibility | Partial | Labelled controls, keyboard navigation and ARIA roles checked by tests; no formal audit with assistive technology |
| Multi-region HA / managed service SLAs | Roadmap | SQLite and one process; do not scale replicas against the same DB |

No market-superiority or AWS compliance equivalence claim is supported by these tests.
