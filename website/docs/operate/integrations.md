---
sidebar_position: 3
---

# Zyvor platform integrations

Each integration is configured by the operator through the environment. Its host must also be on `NUVORA_PROVIDER_HOSTS`, it must use HTTPS for anything but loopback, and redirects are refused. **Govern → Settings → Integrations** shows what is configured and has a **Test** button for each system.

| System | What Nuvora uses it for | Configure |
|---|---|---|
| **Fabric AI gateway** | Private inference: `https://<fabric>/api/ai/openai/<endpoint>/v1` with `fvai_` keys | Model preset; key in `NUVORA_SECRET_FABRIC_KEY` |
| **Gryvia** | GPU model serving: chat and embeddings on `/v1` with a tenant key | Model preset; key in `NUVORA_SECRET_GRYVIA_KEY` |
| **Netra** | Read-only network evidence tools for agents | `NUVORA_NETRA_URL`, `NUVORA_SECRET_NETRA_TOKEN` |
| **Zyntra** | Workflow `handoff` steps: Zyntra's own approvers decide | `NUVORA_ZYNTRA_URL`, `NUVORA_SECRET_ZYNTRA_TOKEN` |
| **Keep** | `run_code` in FluxVM sandboxes, always behind a Nuvora approval | `NUVORA_KEEP_URL`, `NUVORA_SECRET_KEEP_TOKEN`, optional `NUVORA_KEEP_IMAGE` |

## Models: presets and discovery

On **Models → Add model**, pick a preset to fill the provider, base URL and credential reference. Then use **Discover models from this endpoint**, which calls `GET /v1/models`, or `GET /api/tags` for Ollama. It lists the upstream identifiers, with a capability guess for embedding models. The API is `GET /api/models/presets` and `POST /api/models/discover {provider, base_url, key_env?}`, both for administrators.

## Netra tools

Netra tools appear in the agent tool list only when Netra is configured. All of them are read-only `GET` calls:

| Tool | Netra endpoint | Arguments |
|---|---|---|
| `netra_status` | `/api/v1/status` | — |
| `netra_incidents` | `/api/v1/incidents` | `status` (open, resolved or all), `limit` (1–50, default 20) |
| `netra_flow_summary` | `/api/v1/flows/summary` | `window` (15m, 1h or 24h) |
| `netra_drop_explain` | `/api/v1/drops/explain` | `src`, `dst`, optional `port` |

Results pass through the tenant guardrail, which redacts PII and denies blocked topics, before a model sees them.

## Zyntra handoff step

```json
{"id": "decide", "type": "handoff", "action": "restart_service", "scenario": "maintenance",
 "inputs": {"summary": "{{draft}}", "priority": 2}, "depends_on": ["draft"], "timeout_hours": 72}
```

1. The step renders `{{step}}` references in its inputs and calls `POST /api/v1/proposals {action, inputs, scenario}`.
2. The run parks as `waiting_external`.
3. Every five seconds a worker polls `GET /api/v1/proposals/{id}`. On `approved`, `executed` or `completed`, the run resumes with `{status, result, decided_by}` as the step output.
4. On `rejected`, `cancelled` or `expired`, the run stops as `rejected`. After `timeout_hours` it fails.
5. Each outcome is audited as `handoff.<status>`.

You can add the step in the visual workflow builder. Workflows that use it are refused unless Zyntra is configured.

## Keep `run_code`

An agent with the `run_code` tool proposes `{language: python|bash, code}` of up to 20,000 characters. Nothing runs yet: the exact code becomes an approval, and a different approver must accept it.

Once approved, the worker:
1. creates a sandbox with `network: none` and a 120-second lifetime
2. writes `/work/main.py` or `/work/main.sh`
3. runs it with a 60-second deadline
4. deletes the sandbox, even when the run fails

The output keeps `stdout` (20 KB), `stderr` (5 KB) and the exit code, and passes through the guardrail before the agent continues.

## Not yet

- Workload-identity credentials for Fabric and Gryvia.
- Zyntra webhooks instead of polling.
- Keep browser sessions or file artifacts.
- A Verixa adapter.
