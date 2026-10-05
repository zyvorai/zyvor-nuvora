# Implementation roadmap

0.2.0 shipped OIDC SSO, PostgreSQL with replicas, document upload, LLM-judge and grounded evaluations, rerank, live `/v1` streaming, and the Fabric, Gryvia, Netra, Zyntra and Keep integrations. What remains:

## Platform integration

- Workload identity for Fabric and Gryvia instead of static keys; credential rotation.
- Zyntra webhooks instead of polling; Keep browser sessions and file artifacts.
- Verixa adapter for action/outcome release tests.

## Retrieval and data automation

- Document-level authorization before retrieval, connector incremental sync and tombstones.
- OCR in isolated workers, audio/video extraction, human-reviewed structured schemas.
- Citation entailment and source freshness; live embedding-quality benchmarks.
- Retrieval scale benchmarks and vector-store backend adapters (pgvector first).

## Models and optimization

- Explicit provider retry/failover policies with response-start safety.
- Tokenizer-aware estimates and embedding usage/budget accounting.
- Real fine-tuning/distillation submissions through Gryvia with dataset lineage and evaluation-based promotion.
- Quality/latency-aware routing using published evaluation results.

## Enterprise readiness

- SAML, SCIM deprovisioning and back-channel logout; several identity providers per deployment.
- Cluster-wide concurrency limits and budget reservations (today they are per replica).
- Tenant retention/delete/export policies and quotas for every API path.
- Signed audit checkpoints and external immutable storage anchors.
- Complete MCP protocol transport, A2A adapters and OpenTelemetry trace export.
- Formal accessibility audit with assistive technology.

All roadmap entries are absent unless the capability matrix explicitly marks them as implemented. Keep performance and compliance claims tied to independently reproducible evidence.
