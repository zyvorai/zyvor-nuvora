# Validation record — 2026-10-05

## Completed locally

- Python 3.12.14: **80 backend tests passed** (`python3 -m unittest discover -s tests -v`).
- Node 24.19.0: TypeScript check and Vite production build passed.
- Vitest: **15 frontend API and React DOM interaction tests passed**.
- Built the installable Python wheel with `pip wheel --no-build-isolation --no-deps`.
- Extracted the source archive to a clean temporary directory and verified every SHA-256 manifest entry.
- Started the extracted repository without Node or pip installs; the prebuilt console was served.
- SDK smoke: cookie sign-in, demo chat, knowledge-backed answer, scoped token issuance, and bearer inference passed.

Boundary tests cover tenant isolation, roles, CSRF, origins, provider allowlists/redirects, secret-reference constraints, prompt revisions, knowledge replacement, guardrail refusal/redaction, budgets, cache scope, malformed tools, approval fingerprints/expiry/replay/self-approval, job idempotency, workflow pause/resume/branching, agent memory, typed enterprise actions, reviewed endpoint pinning, evaluation gates, partial batch failures, interrupted-job recovery, and audit tampering.

Provider network tests ran against a local HTTP stub for OpenAI-compatible completion, Ollama mapping and embeddings. Action execution was checked with a deterministic substitute, including proving no outbound write occurs before approval. These tests do not measure real model quality or external-system correctness.

- k3s deployment to a single-node lab host with `./scripts/deploy-remote.sh HOST USER`:
  - podman build on the host, image import, Helm install
  - HTTPS NodePort 30789 with a persistent self-signed certificate
  - the PVC bound on `local-path`
  - `/healthz` reachable externally, and a wrong login refused with 401
- The Playwright browser smoke against that deployment: **52 checks passed**.
  - Covers sign-in errors, the mega menu, all 17 pages, and the evaluate-to-runs flow.
  - Covers evidence-chain verification, dark mode persisting across a reload, no horizontal overflow at 390px, and logout.
  - The screenshots in `docs/ux/` are from this run.
- `helm lint`, `helm template`, `shellcheck`, and `scripts/ci-deploy-guards.sh` (32 checks) passed.

## Not completed here

- Multi-node Kubernetes, ingress, and HA tests: only a single k3s node was used.
- Live AWS, GPU, vLLM, Ollama or embedding-model tests: no live endpoint or hardware supplied.
- Bedrock quality/cost/latency benchmark or compliance equivalence: not performed.

GitHub Actions runs the backend matrix, the console build and tests, the deploy checks, and a Chromium smoke test against a local demo server.
