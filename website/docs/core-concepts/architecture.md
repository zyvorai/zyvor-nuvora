---
sidebar_position: 1
---

# Architecture

Nuvora is a Python standard-library HTTP server with SQLite storage and a single background worker. The same origin serves a compiled React console.

![How a request flows through Nuvora](/readme-how-it-works.jpg)

## Request boundary

1. A password session establishes a tenant, user, and role. Service tokens carry a viewer or developer role.
2. Same-origin cookie mutations require the session-derived CSRF token. Bearer API clients are authenticated independently.
3. Every resource lookup includes the tenant in its SQL predicate. An ID alone never authorizes access.
4. Model URLs must match the operator's host allow-list. Remote URLs require HTTPS, credentials are environment references, and redirects are refused.
5. Chat applies the tenant's guardrails before and after generation. Tool arguments are checked before dispatch.
6. The inference ledger records model, usage, configured cost, latency, and cache state. Prompt bodies stay out of the audit ledger.

## Storage

`Store` uses SQLite in WAL mode behind a process-local lock.
- Transactions combine state transitions with their audit events.
- Edits require the expected revision, and versions keep the edited snapshot.
- Re-ingesting a document atomically replaces its chunks, so stale text is never searched.

The database isn't encrypted by Nuvora: use an encrypted volume. Back it up with the SQLite backup API.

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
