# Architecture

NUVORA owns the AI application contract. Fabric owns VM-backed infrastructure and private inference. Gryvia owns Kubernetes GPU workloads, model factories and vector infrastructure. Aurora owns GTM agent logic. Zyntra owns ontology-driven proposals and approved operational decisions.

Fabric and Gryvia integrate through their OpenAI-compatible model endpoints, with presets and model discovery. Netra provides read-only evidence tools for agents. Zyntra receives workflow handoffs and decides them with its own approvers. Keep runs approved code in FluxVM sandboxes. All are configured by the operator (`nuvora/integrations.py`) and share the provider host allow-list.

## Request boundary

1. A password or OIDC session establishes a tenant, user and role. A service token has a viewer/developer role. An OIDC bearer JWT is verified against the issuer JWKS and mapped to a role from its group claim.
2. Same-origin cookie mutations require the session-derived CSRF token. Bearer API clients are independently authenticated.
3. Every resource lookup has tenant in its SQL predicate. IDs alone never authorize access.
4. Model URLs must match the operator's host allowlist. Remote URLs require HTTPS; credentials remain environment references. Redirects are refused.
5. Chat applies the active tenant policy before and after generation. Streamed chat releases text only at sentence boundaries, after the output policy passes. Tool arguments are checked before dispatch.
6. The inference ledger records model, usage, configured cost, latency and cache state. Prompt bodies are not placed in the audit ledger. Jobs can contain their supplied input and tool evidence.

## Storage

`Store` sits on `nuvora/db.py`: SQLite in WAL mode by default, PostgreSQL when `NUVORA_DATABASE_URL` is set. Callers write portable SQL with explicit column lists. The adapter translates placeholders and supplies dialect fragments. `schema_version` records migrations, and replicas migrate one at a time under an advisory lock. Transactions are reentrant and combine state transitions with audit events. Audit appends take a per-tenant advisory lock on PostgreSQL, so replicas cannot fork the chain. Resource edits require the expected revision; versions retain the edited snapshot. Named document reingestion atomically replaces chunks so stale text is not searched.

The database includes application content, user password hashes, token digests, audit events, caches and job evidence. It is not encrypted by this application. Use an encrypted volume and protect filesystem access. The first database file is created mode 0600; SQLite sidecars inherit process/OS permissions. Back up with the SQLite backup API rather than copying a live WAL file alone.

## Retrieval

Text is sliced with bounded overlap. Offline retrieval fuses BM25 and hashed lexical-vector ranks. Hash vectors support reproducibility and require no downloads; they do not understand meaning. A knowledge base may instead reference an external embedding model, whose vectors are saved with each chunk. Query embeddings use that same model and reject incompatible dimensions. Changing the embedding model requires reingestion.

A result includes document identity, source, content digest, chunk position and scores. An AI answer must still be evaluated for citation correctness. The demo provider merely echoes the supplied prompt and does not validate evidence.

## Jobs and execution

Submission pins the resource specification and creator principal. Idempotency keys bind a submission to its exact payload. Each replica runs one worker. A worker atomically claims a queued job (`FOR UPDATE SKIP LOCKED` on PostgreSQL), and each completed workflow/agent step records a checkpoint. Workers heartbeat into the `workers` table. A Zyntra handoff parks a workflow as `waiting_external` until a poller sees Zyntra's decision.

An approval step captures an exact action and SHA-256 fingerprint. Only a different authenticated human with approver/admin authority may decide. The decision validates the fingerprint and job checkpoint atomically. The worker resumes that job and uses its pinned resource revision.

There is no exactly-once guarantee for an external model call if the process dies before its checkpoint is written. Running jobs whose worker stopped heartbeating become `interrupted`; they are not silently replayed. The operator must review their evidence and submit a new run if appropriate. The atomic claim prevents two workers from running one job.

## Guardrails

Deterministic rules deny configured topic substrings, selected instruction-override patterns, and oversize text. PII redaction covers email patterns and long account-number-like sequences. This is not robust jailbreak prevention. Agent execution safety also comes from its closed tool registry, typed arguments, lack of a shell or unrestricted HTTP tool, role checks, and separate-human memory-write approvals.

## Deployment

The API and compiled console share an origin. Local evaluation binds loopback by default. Remote binds require direct TLS or an explicitly configured trusted TLS proxy. SQLite is single-process: the chart then uses one replica and `Recreate`. With PostgreSQL it supports several replicas with rolling updates.

`NUVORA_BEHIND_TLS_PROXY=1` means the operator is responsible for TLS termination and preserving the external Host header. It also enables Secure cookies and HTTPS Origin validation even though the internal hop is HTTP. Do not expose this internal listener directly to the internet.

## Enterprise actions

The action registry gives agents and workflows typed access to operator-selected APIs. GET calls are permitted as read operations; the operator must not register a GET endpoint that mutates state. POST is always staged as an exact-action approval, including the pinned endpoint revision and arguments. Only after independent approval does the worker execute the call. The same host allowlist and credential-reference rules apply as to model providers. Results are limited to 1 MiB and redacted/checked before model use. Automatic POST retries are intentionally absent. Remote precondition/idempotency/outcome guarantees depend on the destination API and are not inferred by NUVORA.
