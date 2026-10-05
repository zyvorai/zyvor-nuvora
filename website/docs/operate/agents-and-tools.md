---
sidebar_position: 7
---

# Agents, tools and prompts

## Tools

Agents choose from the tools you select on the agent. Each tool call is checked against the agent's tool list, budgeted against `max_steps`, and its result is treated as untrusted data.

| Source | How to add | Approval |
|---|---|---|
| Built-in | `knowledge_search` (with an optional metadata filter), `memory_search` and others listed by `GET /api/tools` | Read-only |
| API actions | Register one in **Build → API actions**, or import many with `POST /api/actions/import-openapi {spec, base_url?, operations?}` | POST actions always wait for a different person |
| MCP servers | Add a server in **Build → MCP servers** with its `url`, optional `key_env` and a `readonly` flag; choose which of its tools to expose | Calls to a server that isn't `readonly` wait for a different person |
| Integrations | Netra read tools and Keep `run_code` (see [integrations](./integrations)) | `run_code` always waits |

The OpenAPI importer turns GET and POST operations with flat query or JSON-body inputs into typed actions. MCP tools appear as `mcp_<first 8 characters of the server id>_<tool>`. MCP server hosts must be on `NUVORA_PROVIDER_HOSTS`.

## Memory

Agents can search what the same person stored in earlier sessions with `memory_search`. Writing memory is a consequential step: it waits for approval like any other write. Turn on `summarize_memory` and the agent proposes a summary at the end of a session, which is saved only if it is approved.

## Tracing

Every agent and workflow run records each step's duration. **Runs** shows them as a waterfall. Set `NUVORA_OTEL_ENDPOINT` to export the same spans over OTLP/HTTP to Jaeger, Tempo or any OpenTelemetry collector. Spans carry timings, model names, token counts and costs, never prompt or answer text.

## Prompt variants and experiments

A prompt can carry `variants`, each with its own template and a weight. Rendering picks a variant by weight and keeps that choice stable for the same subject, so one person sees the same wording across requests.

`POST /api/prompts/{id}/experiment {evaluation, variable}` runs the control template and every variant over an evaluation suite's cases. The result shows each arm's score and names a winner only when a variant beats the control.
