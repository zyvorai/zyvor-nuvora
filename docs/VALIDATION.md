# Validation record — 2026-10-05

## Completed locally

- Python 3.12.14: **139 backend tests passed** on SQLite (`python3 -m unittest discover -s tests -v`).
- The same 139 tests passed on PostgreSQL 16 (`NUVORA_TEST_DATABASE_URL=postgresql://…`), including job claims, the advisory-locked audit chain, the shared login throttle, and migration replay.
- `scripts/migrate-sqlite-to-postgres.py` copied a demo database into an empty PostgreSQL database and verified every tenant's audit chain. It refused a non-empty target.
- Node 24.19.0: TypeScript check and Vite production build passed.
- Vitest: **33 frontend tests passed**: API helpers, notifications, password strength, the SSO error message, the evaluation case editor, and React DOM interaction (sign-in, navigation, playground streaming, command palette, shortcuts, drawer history and diff, API keys, logout).
- Built the installable Python wheel with `pip wheel --no-build-isolation --no-deps`.
- Extracted the source archive to a clean temporary directory and verified every SHA-256 manifest entry.
- Started the extracted repository without Node or pip installs; the prebuilt console was served.
- SDK smoke: cookie sign-in, demo chat, knowledge-backed answer, scoped token issuance, and bearer inference passed.

Boundary tests cover tenant isolation, roles, CSRF, origins, provider allowlists/redirects, secret-reference constraints, prompt revisions, knowledge replacement, guardrail refusal/redaction, budgets, cache scope, malformed tools, approval fingerprints/expiry/replay/self-approval, job idempotency, workflow pause/resume/branching, agent memory, typed enterprise actions, reviewed endpoint pinning, evaluation gates, partial batch failures, interrupted-job recovery, and audit tampering.

Provider network tests ran against a local HTTP stub for OpenAI-compatible completion and live streaming, Ollama mapping and embeddings, LLM rerank and LLM-judge cases. SSO ran against a fake identity provider: discovery, PKCE, a signed ID token, the JWKS, and bearer tokens. Netra, Zyntra and Keep ran against stub servers. Action execution was checked with a deterministic substitute, including proving no outbound write occurs before approval. These tests do not measure real model quality or external-system correctness.

- k3s deployment to a single-node lab host with `./scripts/deploy-remote.sh HOST USER`:
  - podman build on the host, image import, Helm install
  - HTTPS NodePort 30789 with a persistent self-signed certificate
  - the PVC bound on `local-path`
  - `/healthz` reachable externally, and a wrong login refused with 401
- The Playwright browser smoke against that deployment: **63 checks passed**.
  - Covers sign-in errors, the mega menu, all 19 pages, and the evaluate-to-runs flow.
  - Covers a two-turn streamed playground conversation, the command palette, the workflow drawer, history and builder, and API key create and revoke.
  - Covers evidence-chain verification, dark mode persisting across a reload, no horizontal overflow at 390px, and logout through the account menu.
  - The screenshots in `docs/ux/` are from this run.
- `helm lint`, `helm template`, `shellcheck`, and `scripts/ci-deploy-guards.sh` (32 checks) passed.

## Not completed here

- Multi-node Kubernetes, ingress, and HA tests: only a single k3s node was used.
- Live AWS, GPU, vLLM, Ollama or embedding-model tests: no live endpoint or hardware supplied.
- A real identity provider (Keycloak, Entra ID, Okta) and live Netra, Zyntra or Keep installs: only stubs were used.
- Several Nuvora replicas on one PostgreSQL inside Kubernetes: the leasing logic is covered by tests, not a multi-pod run.
- Bedrock quality/cost/latency benchmark or compliance equivalence: not performed.

GitHub Actions runs the backend matrix, the PostgreSQL job, the console build and tests, the deploy checks, and a Chromium smoke test against a local demo server.
