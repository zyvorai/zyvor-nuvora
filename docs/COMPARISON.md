# Managed AI platform capability map

This maps the feature areas that managed generative-AI platforms usually offer to what Nuvora ships. It is a design map, not a benchmark. Managed clouds bring hosted infrastructure, licensed model catalogs, regional availability and compliance programs that a self-hosted repository does not reproduce.

| Area | Nuvora | Not included |
|---|---|---|
| Model choice | OpenAI-compatible, Ollama and optional AWS endpoints; Fabric/Gryvia presets and model discovery; price selection and cascade routers; cached-token pricing | Hosted licensed catalog, provisioned throughput |
| Knowledge | File upload (PDF via extra), OCR and transcription, web/S3/Confluence connectors, metadata filters and group ACLs, BM25 + vector fusion, OpenAI/Ollama embeddings, optional LLM rerank, cited passages | Managed scalable indexes, SharePoint and Google Drive connectors |
| Agents | Closed tool registry, OpenAPI import, MCP servers, bounded loops, checkpoints, long-term memory, OTLP traces, Netra evidence tools, Keep sandboxed code behind approval | Managed browser runtime |
| Guardrails | Word and regex filters, checksum-validated PII, grounding score, optional classifier model, applied to inputs, outputs and tool arguments | Formal policy reasoning |
| Flows and prompts | DAG workflows with review, extraction, image and Zyntra handoff steps, visual builder, prompt version snapshots, variant experiments | — |
| Evaluation | Contains/excludes, LLM-judge and grounded cases, per-case reasons, release gates, regression comparison | Large public benchmark suites |
| Customization | LoRA, QLoRA and distillation jobs on your trainer, with resulting models registered; exportable recipes | Hosted GPU training |
| Multimodal | Image input, OCR, transcription, typed extraction, image generation | Video |
| Cost | Usage ledger, token budgets, concurrency caps, exact-match cache, batch jobs | — |
| Enterprise operation | OIDC SSO, tenants, four roles, separate-human approvals, hash-chained audit, PostgreSQL with several replicas | Multi-region HA, SLAs, external audit anchoring |

[CAPABILITIES.md](CAPABILITIES.md) is the source of truth for what is tested and how.

## Where Nuvora differs

1. Customer-controlled deployment and model endpoints, including air-gapped infrastructure.
2. Agent code runs in Keep microVMs with host-controlled credentials and no network.
3. Operational answers cite Netra evidence, and consequential decisions go through Zyntra approvers.
4. One workspace spans VM-backed Fabric and Kubernetes-backed Gryvia model services.

To claim an advantage over any managed platform, measure real tasks on equivalent models and datasets: grounding accuracy, unauthorized action rate, duplicate actions after failures, p95 latency, cost per successful task, and recovery. No such comparison has been performed.
