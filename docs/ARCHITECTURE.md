# Architecture

NUVORA owns the AI application contract. Fabric owns VM-backed infrastructure and private inference. Gryvia owns Kubernetes GPU workloads, model factories and vector infrastructure. Aurora owns GTM agent logic. Zyntra owns ontology-driven proposals and approved operational decisions.

The current integration with Fabric/Gryvia is their OpenAI-compatible model endpoint. Keep, Netra and Zyntra tool bridges are future work, not shipping integrations.

## Request boundary

1. A password session establishes a tenant, user and role. A service token has a viewer/developer role.
2. Same-origin cookie mutations require the session-derived CSRF token. Bearer API clients are independently authenticated.
3. Every resource lookup has tenant in its SQL predicate. IDs alone never authorize access.
4. Model URLs must match the operator's host allowlist. Remote URLs require HTTPS; credentials remain environment references. Redirects are refused.
5. Chat applies the active tenant policy before and after generation. Streamed chat releases text only at sentence boundaries, after the output policy passes. Tool arguments are checked before dispatch.
6. The inference ledger records model, usage, configured cost, latency and cache state. Prompt bodies are not placed in the audit ledger. Jobs can contain their supplied input and tool evidence.

## Storage

`Store` uses SQLite WAL and a process-local reentrant lock. Transactions combine state transitions and audit events where needed. Resource edits require the expected revision; versions retain the edited snapshot. Named document reingestion atomically replaces chunks so stale text is not searched.

The SQLite database includes application content, user password hashes, token digests, audit events, caches and job evidence. It is not encrypted by this application. Use an encrypted volume and protect filesystem access. The first database file is created mode 0600; SQLite sidecars inherit process/OS permissions. Back up with the SQLite backup API rather than copying a live WAL file alone.

## Retrieval

Text is sliced with bounded overlap. Offline retrieval fuses BM25 and hashed lexical-vector ranks. Hash vectors support reproducibility and require no downloads; they do not understand meaning. A knowledge base may instead reference an external embedding model, whose vectors are saved with each chunk. Query embeddings use that same model and reject incompatible dimensions. Changing the embedding model requires reingestion.

A result includes document identity, source, content digest, chunk position and scores. An AI answer must still be evaluated for citation correctness. The demo provider merely echoes the supplied prompt and does not validate evidence.

## Jobs and execution

Submission pins the resource specification and creator principal. Idempotency keys bind a submission to its exact payload. A single worker executes queued jobs; each completed workflow/agent step records a checkpoint.

An approval step captures an exact action and SHA-256 fingerprint. Only a different authenticated human with approver/admin authority may decide. The decision validates the fingerprint and job checkpoint atomically. The worker resumes that job and uses its pinned resource revision.

There is no exactly-once guarantee for an external model call if the process dies before its checkpoint is written. On restart, previously running jobs become `interrupted`; they are not silently replayed. The operator must review their evidence and submit a new run if appropriate. In-process duplicate execution of one job is prevented by a job lock.

## Guardrails

Deterministic rules deny configured topic substrings, selected instruction-override patterns, and oversize text. PII redaction covers email patterns and long account-number-like sequences. This is not robust jailbreak prevention. Agent execution safety also comes from its closed tool registry, typed arguments, lack of a shell or unrestricted HTTP tool, role checks, and separate-human memory-write approvals.

## Deployment

The API and compiled console share an origin. Local evaluation binds loopback by default. Remote binds require direct TLS or an explicitly configured trusted TLS proxy. SQLite is single-process; the supplied chart uses one replica and `Recreate` deployment strategy.

`NUVORA_BEHIND_TLS_PROXY=1` means the operator is responsible for TLS termination and preserving the external Host header. It also enables Secure cookies and HTTPS Origin validation even though the internal hop is HTTP. Do not expose this internal listener directly to the internet.

## Enterprise actions

The action registry gives agents and workflows typed access to operator-selected APIs. GET calls are permitted as read operations; the operator must not register a GET endpoint that mutates state. POST is always staged as an exact-action approval, including the pinned endpoint revision and arguments. Only after independent approval does the worker execute the call. The same host allowlist and credential-reference rules apply as to model providers. Results are limited to 1 MiB and redacted/checked before model use. Automatic POST retries are intentionally absent. Remote precondition/idempotency/outcome guarantees depend on the destination API and are not inferred by NUVORA.
