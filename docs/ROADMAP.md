# Implementation roadmap

0.2.0 shipped OIDC SSO, PostgreSQL with replicas, document upload, LLM-judge and grounded evaluations, rerank, live `/v1` streaming, and the Fabric, Gryvia, Netra, Zyntra and Keep integrations. 0.3.0 added guardrails v2, cascade routers, prompt experiments, OpenAPI and MCP tools, long-term memory, OTLP traces, image input, OCR and transcription, extraction review, web/S3/Confluence connectors, document ACLs, trainer-backed training and image generation. What remains:

## Platform integration

- Workload identity for Fabric and Gryvia instead of static keys; credential rotation.
- Zyntra webhooks instead of polling; Keep browser sessions and file artifacts.
- Verixa adapter for action/outcome release tests.

## Retrieval and data automation

- SharePoint and Google Drive connectors; group sync from the identity provider.
- OCR in isolated workers; video extraction.
- Citation entailment (lexical overlap and freshness boosting shipped; entailment models remain); live embedding-quality benchmarks.
- Retrieval scale benchmarks and vector-store backend adapters (pgvector first).

## Models and optimization

- Response-start-safe stream retries and multi-hop health-aware failover (buffered `max_retries` and single `failover_model` shipped).
- Model-tokenizer estimates (characters/4 heuristic and embedding budget metering shipped).
- Gryvia as a trainer, dataset lineage and evaluation-based promotion of trained models.
- Latency-aware and learned routing using published evaluation results.
- A batch inference API with provider batch discounts.

## Enterprise readiness

- SAML, SCIM deprovisioning and back-channel logout; several identity providers per deployment.
- Cluster-wide concurrency limits and budget reservations (today they are per replica).
- Tenant retention/delete/export policies and quotas for every API path.
- Signed audit checkpoints and external immutable storage anchors.
- Complete MCP protocol transport (streaming sessions) and A2A adapters.
- Timezone-aware cron calendars and rich Slack/Teams apps (5-field UTC cron, Slack/Teams/email webhook shapes, and an evaluation release board shipped).
- Deeper evaluation dashboards across releases and promotion gates (suite release board shipped).
- Formal accessibility audit with assistive technology.

All roadmap entries are absent unless the capability matrix explicitly marks them as implemented. Keep performance and compliance claims tied to independently reproducible evidence.
