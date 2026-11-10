---
sidebar_position: 9
title: Schedules, webhooks and bundles
---

# Schedules, webhooks and bundles

Keep agents running on a clock, notify other systems when work finishes, and move configuration between environments without copying secrets.

## Scheduled agents

Create a `schedules` resource with an agent id and either:

- `every_minutes` (1–10 080), or
- `cron` — a 5-field UTC expression (`minute hour day-of-month month day-of-week`), supporting `*`, `*/n`, ranges and lists

The background worker checks about once a minute. `POST /api/schedules/{id}/run` enqueues immediately without waiting for the tick.

```bash
curl -sS -H "Authorization: Bearer $NUVORA_TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"Weekday brief","agent":"AGENT_ID","cron":"0 9 * * 1-5","prompt":"Summarise overnight incidents."}' \
  "$NUVORA_URL/api/schedules"
```

## Outbound webhooks

Administrators register a `webhooks` resource with events, an HMAC secret (≥16 chars) and a format:

| Format | Destination | Body |
|---|---|---|
| `generic` | `url` http(s) | `{event, at, data}` |
| `slack` | Incoming webhook URL | `{text, nuvora}` |
| `teams` | Connector URL | MessageCard + `nuvora` |
| `email` | `to` address | Needs `NUVORA_SMTP_HOST` (+ port/user/password/from) |

Events: `job.completed`, `job.failed`, `approval.created`, `approval.decided`, `document.ingested`, `connector.synced`, `guardrail.blocked`.

POSTs carry `X-Nuvora-Signature: sha256=<hex>` and retry up to `max_retries` (0–5) on failure. `POST /api/webhooks/{id}/test` sends a synthetic `job.completed`. Secrets are redacted on read.

## Config bundles

- `GET /api/bundles/export` — agents, prompts, policies, workflows, guardrails, routers, schedules, MCP servers, connectors (no secrets)
- `POST /api/bundles/import` — admin; `dry_run: true` previews creates

Use **Settings → Config bundles** in the console for the same flow.
