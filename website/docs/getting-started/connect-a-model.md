---
sidebar_position: 3
---

# Connect a real model

The demo model only echoes. To get real answers, point Nuvora at a model endpoint you run or trust.

```bash
export NUVORA_PROVIDER_HOSTS='localhost,127.0.0.1,inference.internal.example'
export NUVORA_SECRET_VLLM='your-provider-key'
python3 -m nuvora.server
```

On k3s, pass the allow-list to the deploy script instead: `NUVORA_PROVIDER_HOSTS=... ./scripts/deploy-remote.sh HOST USER`.

## Adapters

| Provider | Use it for | Notes |
|---|---|---|
| `openai` | vLLM, llama.cpp, Fabric, Gryvia, any OpenAI-compatible server | Supports tool calls; use it for agents |
| `ollama` | Native Ollama at `http://127.0.0.1:11434` | For agents, use Ollama's `/v1` endpoint with `openai` |
| `bedrock` | AWS Bedrock Converse | `pip install '.[aws]'`; standard AWS credential chain; no tools |
| `demo` | Offline evaluation | Synthetic, and always labeled |

## Rules the server enforces

- **Allow-list.** The host must exactly match an entry in `NUVORA_PROVIDER_HOSTS`. Redirects are refused.
- **HTTPS.** Remote hosts need HTTPS. Plain HTTP is accepted only for loopback.
- **Secrets by reference.** A model stores the *name* of a `NUVORA_SECRET_*` variable, never its value.

## Routing

You can choose a provider explicitly in Playground, or use `auto`:
- `auto` picks the lowest configured input-plus-output price among the real chat providers that are enabled.
- It falls back to the demo only when no real provider exists.
- This is price-based routing, not a quality-aware router.
