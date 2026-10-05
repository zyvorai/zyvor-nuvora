# Validation record — 2026-10-05

## Completed locally

- Python 3.14.7: **199 backend tests passed** on SQLite (`python3 -m unittest discover -s tests -v`).
- The same 199 tests passed on PostgreSQL 16 (`NUVORA_TEST_DATABASE_URL=postgresql://…`), including job claims, the advisory-locked audit chain, the shared login throttle, and migration replay.
- `scripts/migrate-sqlite-to-postgres.py` copied a demo database into an empty PostgreSQL database and verified every tenant's audit chain. It refused a non-empty target.
- Node 24.19.0: TypeScript check and Vite production build passed.
- Vitest: **44 frontend tests passed**: API helpers, navigation groups, notifications, password strength, the SSO error message, the evaluation case editor, and React DOM interaction (sign-in, navigation, playground streaming, command palette, shortcuts, drawer history and diff, API keys, logout).
- Built the installable Python wheel with `pip wheel --no-build-isolation --no-deps`.
- Extracted the source archive to a clean temporary directory and verified every SHA-256 manifest entry.
- Started the extracted repository without Node or pip installs; the prebuilt console was served.
- SDK smoke: cookie sign-in, demo chat, knowledge-backed answer, scoped token issuance, and bearer inference passed.

Boundary tests cover tenant isolation, roles, CSRF, origins, provider allowlists/redirects, secret-reference constraints, prompt revisions, knowledge replacement, guardrail refusal/redaction, budgets, cache scope, malformed tools, approval fingerprints/expiry/replay/self-approval, job idempotency, workflow pause/resume/branching, agent memory, typed enterprise actions, reviewed endpoint pinning, evaluation gates, partial batch failures, interrupted-job recovery, and audit tampering.

0.3.0 adds tests for guardrail filters, PII checksums, grounding and a fail-closed classifier; router escalation and cached-token pricing; prompt variants and experiments; OpenAPI import and MCP tools with approval; long-term memory and OTLP export; image content parts, OCR and transcription ingest; extraction review; web, S3 and Confluence sync; metadata filters and group ACLs; trainer jobs and model registration; and image generation with expiring artifacts.

Provider network tests ran against a local HTTP stub for OpenAI-compatible completion and live streaming, Ollama mapping and embeddings, LLM rerank and LLM-judge cases. SSO ran against a fake identity provider: discovery, PKCE, a signed ID token, the JWKS, and bearer tokens. Netra, Zyntra, Keep, MCP servers, connector sources, the trainer and image endpoints ran against stub servers. Action execution was checked with a deterministic substitute, including proving no outbound write occurs before approval. These tests do not measure real model quality or external-system correctness.

- k3s deployment of 0.3.0 to a single-node lab host with `./scripts/deploy-remote.sh HOST USER`, using a generated administrator password:
  - podman build on the host, image import, Helm install
  - HTTPS NodePort 30789 with a persistent self-signed certificate
  - the PVC bound on `local-path`
  - `/healthz` reachable externally, and a wrong login refused with 401
- The Playwright browser smoke against the 0.3.0 deployment: **77 checks passed** (78 with `NUVORA_EXPECT_SSO=1`, where the extra check covers the SSO button against a fake identity provider).
  - Covers sign-in errors, the mega menu, all 22 pages, and the evaluate-to-runs flow.
  - Covers a two-turn streamed playground conversation, image generation in the Playground, the command palette, the workflow drawer, history and builder, and API key create and revoke.
  - Covers document upload, retrieval and delete, pasted text, the evaluation case editor with an LLM judge, per-case results, and the Integrations card.
  - Covers evidence-chain verification, dark mode persisting across a reload, no horizontal overflow at 390px, and logout through the account menu.
  - The screenshots in `docs/ux/` are from this run.
- `helm lint`, `helm template` (including the `env` and `envFromSecret` rejection paths), and `scripts/ci-deploy-guards.sh` (34 checks) passed.

## Live models (CPU-only lab host)

`scripts/e2e-live.py` ran against Nuvora on loopback and Ollama 0.32 on the same 12-core host, without a GPU. **16 of 16 checks passed** with `NUVORA_PROVIDER_TIMEOUT=300`:
- qwen2.5:1.5b for chat, `/v1` streaming, grounded answers (2 citations), the classifier, extraction and the router judge
- qwen2.5:0.5b as the router's first tier, qwen2.5:3b for the agent, granite3.2-vision for vision and OCR, nomic-embed-text for embeddings
- PII masking and blocking, word filters, metadata filters, the usage ledger and audit verification

What the run showed:
- The classifier blocked a request for weapon instructions (violence, misconduct, prompt attack) and allowed a soup recipe.
- OCR of a printed note read both lines, but dropped one digit from a ticket number and repeated one line.
- qwen2.5:1.5b and moondream are too small for some tasks. The 1.5B model answers without calling tools, and moondream returns empty answers for the OCR and colour prompts. qwen2.5:3b called the tool, but still missed the answer in the retrieved passage.
- qwen2.5:1.5b returns extraction fields without confidences. Nuvora now keeps those values at confidence 0.
- The router's first tier passed the judge every time, so this run did not observe an escalation.
- With the default 45-second timeout, a grounded answer on CPU timed out, which is why `NUVORA_PROVIDER_TIMEOUT` exists.

These results show that the adapters work end to end with real models. They do not measure answer quality.

## Not completed here

- Multi-node Kubernetes, ingress, and HA tests: only a single k3s node was used.
- Live AWS, GPU, vLLM, transcription or image-model tests: no live endpoint or hardware supplied. Ollama chat, embedding, vision and classifier models ran on CPU only (see above).
- A live trainer, MCP server, S3 bucket or Confluence space: only stubs were used.
- A real identity provider (Keycloak, Entra ID, Okta) and live Netra, Zyntra or Keep installs: only stubs were used.
- Several Nuvora replicas on one PostgreSQL inside Kubernetes: the leasing logic is covered by tests, not a multi-pod run.
- Quality, cost or latency benchmarks against managed AI platforms: not performed.

GitHub Actions runs the backend matrix, the PostgreSQL job, the console build and tests, the deploy checks, and a Chromium smoke test against a local demo server.
