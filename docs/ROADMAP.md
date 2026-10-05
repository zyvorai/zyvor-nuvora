# Implementation roadmap

## Next: real platform integration

- Fabric and Gryvia provider discovery and credentials with workload identity.
- Keep execution backend: ephemeral cells, browser/code/tool execution, host-brokered secrets.
- Netra read-only investigation and Zyntra proposal tools with independent approval authority.
- Verixa adapter for action/outcome release tests.

## Retrieval and data automation

- Document-level authorization before retrieval, connector incremental sync and tombstones.
- PDF/OCR parsers in isolated workers, audio/video extraction, human-reviewed structured schemas.
- Reranking, semantic retrieval quality tests, citation entailment and source freshness.
- Retrieval scale benchmarks and vector-store backend adapters.

## Models and optimization

- Live upstream streaming on `/v1/chat/completions` (the console stream is live already), and Bedrock ConverseStream.
- Explicit provider retry/failover policies with response-start safety.
- Tokenizer-aware estimates and embedding usage/budget accounting.
- Real fine-tuning/distillation submissions through Gryvia with dataset lineage and evaluation-based promotion.
- Quality/latency-aware routing using published evaluation results.

## Enterprise readiness

- OIDC/SAML through Haven; service identity and credential rotation.
- Postgres-backed state, leased distributed workers, idempotent external actions and HA.
- Tenant retention/delete/export policies, quotas for every API path, scalable login throttling.
- Signed audit checkpoints and external immutable storage anchors.
- Complete MCP protocol transport, A2A adapters and OpenTelemetry trace export.
- Formal accessibility audit with assistive technology.

All roadmap entries are absent unless the capability matrix explicitly marks them as implemented. Keep performance and compliance claims tied to independently reproducible evidence.
