---
sidebar_position: 8
---

# Connectors and document access

Connectors keep a knowledge base in step with a source. They are administrator resources, managed in **Workspace → Connectors**.

## Allow the hosts first

Connectors only reach hosts the operator lists:

```bash
export NUVORA_CONNECTOR_HOSTS='docs.example.com,wiki.example.com,s3.eu-west-1.amazonaws.com'
```

With the variable empty (the default), every connector is refused. Redirects are not followed.

## Sources

| Type | Fields | Notes |
|---|---|---|
| `web` | `url`, `depth`, `max_pages` (default 25, up to 200) | Same host only, honours `robots.txt` |
| `s3` | `bucket`, `prefix`, `region`, `key_env` | Versioned by ETag |
| `confluence` | `url`, `space`, `username`, `key_env`, `max_pages` (default 100, up to 500) | Bearer or basic auth; versioned by page version |

Credentials always come from `NUVORA_SECRET_*` environment variables, never from the resource itself.

## Sync

`POST /api/connectors/{id}/sync` runs an incremental sync as a job: new items are added, changed ones re-ingested, unchanged ones skipped, and items gone from the source removed. Set `interval_minutes` (15–10080) and the worker syncs on that schedule.

## Metadata and access groups

Every document can carry `metadata` (key/value pairs) and `groups`. Connectors stamp their own `metadata` and `groups` on what they ingest; uploads and `ingest` accept them too.

- **Filters:** `POST /api/retrieve` and `/api/answer` take a `filter` such as `{"region": "eu", "team": {"in": ["ops", "sre"]}}`. The agent `knowledge_search` tool accepts the same filter.
- **Access:** a document with `groups` is visible only to members of at least one of those groups, and to administrators. That applies to listing, retrieval and answers alike.

Members get groups in **Govern → Access** or with `POST /api/users/{username} {groups}`. With single sign-on, groups come from the identity provider's groups claim on every login.
