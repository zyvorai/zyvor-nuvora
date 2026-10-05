---
sidebar_position: 1
---

# Architecture

Nuvora is a Python standard-library HTTP server with a background worker and a compiled React console on the same origin. It stores data in SQLite by default, or in PostgreSQL for several replicas. Optional extras add PDF parsing (`pdf`), SSO bearer verification (`sso`), PostgreSQL (`postgres`) and AWS models (`aws`); the container image bundles all of them.

![How a request flows through Nuvora](/readme-how-it-works.jpg)

## Request boundary

1. A password session establishes a tenant, user, and role. Service tokens carry a viewer or developer role.
2. Same-origin cookie mutations require the session-derived CSRF token. Bearer API clients are authenticated independently.
3. Every resource lookup includes the tenant in its SQL predicate. An ID alone never authorizes access.
4. Model URLs must match the operator's host allow-list. Remote URLs require HTTPS, credentials are environment references, and redirects are refused.
5. Chat applies the tenant's guardrails before and after generation. Tool arguments are checked before dispatch.
6. The inference ledger records model, usage, configured cost, latency, and cache state. Prompt bodies stay out of the audit ledger.
7. `/api/chat/stream` sends server-sent events. Text is held until a sentence boundary and checked against the output guardrails before it's released.

## Storage

`Store` talks to a small adapter (`nuvora/db.py`): SQLite in WAL mode, or PostgreSQL when `NUVORA_DATABASE_URL` is set. A `schema_version` table tracks migrations. On PostgreSQL, jobs are claimed with `FOR UPDATE SKIP LOCKED`, audit appends are serialised per tenant with an advisory lock, and the login throttle is shared. See [PostgreSQL and replicas](../operate/postgres.md).
- Transactions combine state transitions with their audit events.
- Edits require the expected revision, and versions keep the edited snapshot.
- Re-ingesting a document atomically replaces its chunks, so stale text is never searched.

The database isn't encrypted by Nuvora: use an encrypted volume. Back up SQLite with its backup API, and PostgreSQL with your usual tooling.

## Retrieval

Text is sliced into chunks with bounded overlap. Offline retrieval fuses BM25 ranks with hashed lexical-vector ranks.
- This is reproducible and needs no downloads, but it doesn't understand meaning.
- A knowledge base can reference an external embedding model instead.
- Every result carries the document identity, source, content digest, chunk position, and scores.

## Jobs

When a run is submitted, Nuvora pins the resource specification and the creator.
- Idempotency keys bind a submission to its exact payload.
- One worker executes jobs and writes a checkpoint after each step.
- On restart, jobs that were running become `interrupted`. They're never silently replayed.

## Where it sits

Nuvora is the application layer above Zyvor's infrastructure projects:
- **Fabric:** VM-backed infrastructure and private inference.
- **Gryvia:** Kubernetes GPU workloads.

Today, Nuvora integrates with them through their OpenAI-compatible model endpoints.
