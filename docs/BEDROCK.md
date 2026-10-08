# Bedrock-compatible API

Nuvora speaks the Amazon Bedrock wire format, so the AWS SDKs (boto3 and others) and the `aws` CLI can manage and call a Nuvora server by pointing `endpoint_url` at it. This is the **inbound** door. It is a different thing from the optional `aws` *provider* (outbound: Nuvora calling Bedrock Converse in your AWS account), which is still unvalidated against a live account.

**Status: preview.** Verified with boto3/botocore and, for the commands listed under [Verification record](#verification-record), the `aws` CLI, against a local Nuvora and its offline demo provider. Not run against AWS, Terraform, CDK or a real trainer. There is no claim of behavioural or compliance equivalence with Amazon Bedrock.

## What it is and is not

It is:

- Four Bedrock services (`bedrock-runtime`, `bedrock`, `bedrock-agent`, `bedrock-agent-runtime`) over Nuvora's own resources. A guardrail, knowledge base or agent created through boto3 is the same object the console and `/api/*` show, with Nuvora's roles, validation, budgets, usage ledger and audit.
- SigV4 header authentication with access keys Nuvora issues, or `Authorization: Bearer <Nuvora token>`.
- Honest about gaps: a member Nuvora cannot honour is a `ValidationException` naming it, an operation it does not implement is `501 UnsupportedOperationException`. Nothing is silently accepted.

It is not:

- Amazon Bedrock. No Amazon models, no Amazon guardrail engine (guardrails are Nuvora's deterministic rules plus an optional classifier model), no S3, IAM, KMS, CloudWatch or OpenSearch behind it.
- A way to use Bedrock model ids. `anthropic.claude-…` is not an alias: register the model in Nuvora and use its id.
- A target for the compatibility scripts when it is `*.amazonaws.com`: the scripts refuse that.

## Setup

1. Set `NUVORA_SECRET_KEY` (32+ characters, `openssl rand -hex 32`) before starting the server. SigV4 needs the secret to recompute signatures, so Nuvora stores issued secrets encrypted under this key. Without it no access key can be issued or used. Bearer tokens do not need it. See [OPERATIONS.md](OPERATIONS.md).
2. Start Nuvora (`python3 -m nuvora.server --demo` for the offline demo provider) and sign in as admin.
3. Issue an access key (the secret is shown once):

   ```bash
   curl -s -X POST $NUVORA/api/aws-credentials -H "Authorization: Bearer $ADMIN_TOKEN" \
     -H 'Content-Type: application/json' -d '{"role":"developer","label":"my laptop"}'
   ```

4. Admin writes need a bearer token (below). Get one from `POST /api/login` (the `nuvora_session` cookie value) or, for viewer or developer service tokens, `POST /api/tokens`.

### Credentials and roles

| Credential | Signs with | Role it can have |
|---|---|---|
| Access key (`NVRA…`) from `/api/aws-credentials` | SigV4 | viewer or developer, never above its user |
| Bearer token (session, service token or OIDC JWT) | `Authorization: Bearer` | whatever the token's user has, including admin |

AWS access keys are **capped at developer**. Operations that Nuvora gates on admin are therefore reachable only with a bearer token of an admin user:

- the whole `bedrock` control-plane write surface (guardrails, customization and evaluation jobs, logging configuration, tags);
- in `bedrock-agent`: deleting a knowledge base, agent or data source, creating or changing data sources and action groups, `StartIngestionJob`.

Everything else (runtime inference, Retrieve, InvokeAgent, creating knowledge bases and agents, aliases, versions, associations) works with a developer key. Reads work for any role.

`AWS_BEARER_TOKEN_BEDROCK` is read by boto3 and the CLI for `bedrock` and `bedrock-runtime`. For `bedrock-agent` it is not (the CLI answers `NoCredentials`), so add the header yourself, as `scripts/bedrock/_common.py` does.

### boto3

```python
import boto3

kwargs = dict(endpoint_url='http://127.0.0.1:8789', region_name='us-east-1',
              aws_access_key_id='NVRA…', aws_secret_access_key='…')
runtime = boto3.client('bedrock-runtime', **kwargs)
out = runtime.converse(modelId='<nuvora model id>',
                       messages=[{'role': 'user', 'content': [{'text': 'Hello'}]}])
```

Any region is accepted. For bearer auth set `AWS_BEARER_TOKEN_BEDROCK=<token>` and omit the keys (`bedrock`, `bedrock-runtime`).

Caution: when `AWS_BEARER_TOKEN_BEDROCK` is in the environment, botocore uses it and ignores the access key for those services, so a "SigV4 test" in such a shell is really a bearer test.

### aws CLI

```bash
export AWS_ACCESS_KEY_ID=NVRA… AWS_SECRET_ACCESS_KEY=… AWS_DEFAULT_REGION=us-east-1
E=http://127.0.0.1:8789
aws bedrock list-foundation-models --endpoint-url $E
aws bedrock-runtime converse --endpoint-url $E --model-id <nuvora model id> \
  --messages '[{"role":"user","content":[{"text":"Hello"}]}]'
aws bedrock-agent list-knowledge-bases --endpoint-url $E
aws bedrock-agent-runtime retrieve --endpoint-url $E --knowledge-base-id <id> --retrieval-query text="refund policy"
# admin write: bearer token instead of keys
AWS_BEARER_TOKEN_BEDROCK=$ADMIN_TOKEN aws bedrock create-guardrail --endpoint-url $E --name g \
  --blocked-input-messaging a --blocked-outputs-messaging b
```

aws-cli 2.36.42 has no `bedrock-runtime converse-stream` subcommand, so streaming is exercised through the SDK only.

## Operations

Status key: **real** = implemented over Nuvora resources and exercised by `scripts/bedrock/`; **recorded** = the route is recognised and answers `501 UnsupportedOperationException`; **refused** = the operation works but specific members or modes are rejected by name with `ValidationException`. Roles: R = any role, D = developer, A = admin (bearer token).

### bedrock-runtime

| Operation | Status | Role | Notes |
|---|---|---|---|
| Converse | real, refused | D | Same pipeline as `/v1/chat/completions`: routing, tenant guardrails, budget, usage, audit. Refused by name: `additionalModelRequestFields`, `promptVariables`, `requestMetadata`, `performanceConfig`, `serviceTier`, document/video/guardContent/reasoning/cachePoint/citations blocks |
| ConverseStream | real | D | `messageStart`, `contentBlockStart/Delta/Stop`, `messageStop`, `metadata`. Text released at sentence boundaries after the output guardrail |
| InvokeModel | real | D | Nuvora/OpenAI chat body, Anthropic messages body (`bedrock-2023-05-31`), embeddings body |
| InvokeModelWithResponseStream | real | D | The two chat shapes; embedding models refused |
| CountTokens | real, estimate | D | characters / 4, not a tokenizer |
| ApplyGuardrail | real, refused | D | Nuvora guardrail resources; `query` qualifier refused |
| StartAsyncInvoke, GetAsyncInvoke, ListAsyncInvokes | recorded | | 501 |

### bedrock (control plane)

| Operation | Status | Role | Notes |
|---|---|---|---|
| ListFoundationModels, GetFoundationModel | real | R | From the tenant's enabled models; `modelId` is the Nuvora id |
| CreateGuardrail, UpdateGuardrail, DeleteGuardrail, CreateGuardrailVersion | real, refused | A | DRAFT plus immutable numbered versions; topics are keyword-only; `kmsKeyId`, managed word lists, `INSULTS` etc. refused |
| GetGuardrail, ListGuardrails | real | R | Pagination via `maxResults`/`nextToken` |
| ListInferenceProfiles, GetInferenceProfile | real | R | Every router is an `APPLICATION` profile; no `SYSTEM_DEFINED` ones |
| CreateInferenceProfile, DeleteInferenceProfile | recorded | | 501 |
| Put/Get/DeleteModelInvocationLoggingConfiguration | real, refused | A for writes | Only a configuration that delivers nothing is accepted (no S3 or CloudWatch) |
| CreateModelCustomizationJob, GetModelCustomizationJob, ListModelCustomizationJobs | real | A for create | LoRA and distillation through the external trainer; **503 `ServiceUnavailableException` when `NUVORA_TRAINER_URL` is unset** |
| StopModelCustomizationJob | recorded | | 501 while in progress, 409 once finished |
| CreateEvaluationJob, GetEvaluationJob, ListEvaluationJobs | real, refused | A for create | Custom task type; `Nuvora.Assertions/Judge/Grounded` metrics; `Builtin.*`, human and RAG evaluation refused |
| StopEvaluationJob | recorded | | 501 while in progress, 409 once finished |
| TagResource, UntagResource, ListTagsForResource | real | A for writes | Guardrails only; other ARN kinds are `ValidationException` |

### bedrock-agent

| Operation | Status | Role | Notes |
|---|---|---|---|
| CreateKnowledgeBase, UpdateKnowledgeBase, Get/ListKnowledgeBases | real, refused | D writes | VECTOR with a Nuvora embedding model, built-in store only; OpenSearch, Pinecone, RDS etc. refused. `roleArn` is recorded, never used |
| DeleteKnowledgeBase | real | A | 409 while data sources or agent associations exist |
| CreateDataSource, UpdateDataSource, DeleteDataSource | real, refused | A | WEB, S3, CONFLUENCE connectors; WEB and CONFLUENCE need the server's `NUVORA_CONNECTOR_HOSTS` to allow the host; other types refused |
| GetDataSource, ListDataSources | real | R | |
| StartIngestionJob | real | A | `STARTING`, `IN_PROGRESS`, `COMPLETE`, `FAILED`; one job per knowledge base |
| GetIngestionJob, ListIngestionJobs | real | R | |
| CreateAgent, UpdateAgent, PrepareAgent, Get/ListAgents | real, refused | D | `NOT_PREPARED` until `PrepareAgent`; prompt overrides, custom orchestration, collaboration refused |
| DeleteAgent | real | A | 409 with aliases unless `skipResourceInUseCheck` |
| ListAgentVersions, GetAgentVersion | real | R | |
| DeleteAgentVersion | recorded | | 501 |
| CreateAgentAlias, UpdateAgentAlias, DeleteAgentAlias, Get/ListAgentAliases | real | D | An alias routes to exactly one numbered version; creating one without routing snapshots a version |
| Create/Update/Delete AgentActionGroup | real, refused | A | Inline OpenAPI JSON only; Lambda executors, function schemas, `RETURN_CONTROL` refused |
| Get/ListAgentActionGroups | real | R | |
| Associate/Update/DisassociateAgentKnowledgeBase, Get/ListAgentKnowledgeBases | real | D | DRAFT only for writes |
| TagResource, UntagResource, ListTagsForResource | real | D | Knowledge bases, agents, aliases |

### bedrock-agent-runtime

| Operation | Status | Role | Notes |
|---|---|---|---|
| Retrieve | real | D | Filters `equals`, `in`, `andAll`; `numberOfResults` is the page size, paged with `nextToken` over a pool of at most 20 passages |
| RetrieveAndGenerate | real, refused | D | `KNOWLEDGE_BASE` only; `EXTERNAL_SOURCES`, orchestration and inference config refused. One whole-answer citation |
| InvokeAgent | real, refused | D | A Platform agent job streamed as `chunk` (+ `trace` when enabled). The alias decides what runs: `TSTALIASID` is the DRAFT, any other alias runs its pinned numbered version (model, instruction, tools from that version's action groups, knowledge bases, guardrail, max steps); unknown alias is 404, an alias whose version or action is gone is `ConflictException`, `REJECT_INVOCATIONS` is `ValidationException`; `memoryId`, `sessionState`, streaming configuration refused. A run waiting for approval is `ConflictException` |
| GetAgentMemory, DeleteAgentMemory | recorded | | 501 |
| InvokeFlow and other flow operations | recorded | | 501 |

Every Bedrock operation Nuvora recognises but does not implement answers 501; anything unrecognised is `UnknownOperationException`. Details per operation are in [API.md](API.md#bedrock-compatible-api-preview).

## ARN scheme

ARNs are Nuvora's, not AWS's: `arn:nuvora:bedrock:<region>:<tenant>:<kind>/<id>`.

| Kind | Resource part |
|---|---|
| Foundation model | `foundation-model/<model id>` (no tenant) |
| Guardrail | `guardrail/<id>` |
| Inference profile | `inference-profile/<router id>` |
| Model customization job, evaluation job, custom model | `model-customization-job/<id>`, `evaluation-job/<id>`, `custom-model/<model id>` |
| Knowledge base, agent | `knowledge-base/<id>`, `agent/<id>` |
| Agent alias | `agent-alias/<agentId>/<aliasId>` |

The region is the SigV4 credential-scope region (`local` for bearer tokens) and is ignored on the way in. The tenant must be the caller's. Wherever Bedrock takes an identifier or an ARN, both work. Locations that Bedrock writes as S3 URIs are `nuvora://datasets/<id>`, `nuvora://evaluations/<id>` and `nuvora://jobs`; `s3://` locations are refused.

## Known differences from AWS

- Ids are Nuvora's 20 hex characters for knowledge bases, agents, data sources and guardrails; alias and action group ids are 10 characters.
- Model ids are Nuvora model ids (or `router:<id>`, or an ARN around either).
- `stopReason` is derived (`tool_use`, `max_tokens`, `end_turn`, `guardrail_intervened`); `stop_sequence` and `content_filtered` are never returned. `CountTokens` is an estimate.
- Guardrail assessments are mapped from Nuvora findings where an equivalent exists; confidence is a lower bound from the configured strength; units are computed but not billed.
- Control-plane operations are synchronous: create returns the final state (`ACTIVE`, `NOT_PREPARED`), delete returns `DELETING` and the resource is already gone.
- IAM roles in requests (`roleArn`, `agentResourceRoleArn`) are recorded and echoed but never used. KMS, VPC, S3 and Lambda members are refused.
- Only SigV4 header signing and bearer tokens: no presigned URLs, no streaming chunk signing, no session tokens.
- Access keys are capped at developer and many writes need an admin bearer token (see above), which AWS has no equivalent of.
- Twenty authentication failures in five minutes from one address answer 429.

## Compatibility suite

`scripts/bedrock/` holds boto3 scripts that exercise a **running** Nuvora, one per service group, plus a runner:

| Script | Covers |
|---|---|
| `compat_runtime.py` | bedrock-runtime and model listing |
| `compat_agent_runtime.py` | Retrieve, RetrieveAndGenerate, InvokeAgent |
| `compat_control.py` | `bedrock` control plane |
| `compat_agent_control.py` | `bedrock-agent` control plane |
| `run-compat.sh` | Starts a throwaway local Nuvora (demo provider, temp data dir, free port, generated secrets), issues a developer key and an admin bearer token, runs the four scripts, prints the combined table and tears everything down |

```bash
pip install '.[aws]'
scripts/bedrock/run-compat.sh            # or: PYTHON=/path/to/python scripts/bedrock/run-compat.sh
```

Against your own server:

```bash
export NUVORA_ENDPOINT=https://nuvora.example.com
export AWS_ACCESS_KEY_ID=NVRA… AWS_SECRET_ACCESS_KEY=…    # developer key
export AWS_BEARER_TOKEN_BEDROCK=…                         # admin token, for admin-only operations
python scripts/bedrock/compat_control.py --region us-east-1
```

Each script creates throwaway resources, removes them in `finally`, prints a per-operation `PASS`/`FAIL`/`SKIP` table, exits nonzero on any `FAIL`, and refuses an `*.amazonaws.com` endpoint. Without a bearer token, admin-only checks are `SKIP`. Operations that need server-side configuration are `SKIP` with the reason (for example model customization without `NUVORA_TRAINER_URL`).

## Verification record

Run on 2026-10-08, macOS (arm64), Python 3.14.7, boto3 and botocore 1.43.108, aws-cli 2.36.42, against `python -m nuvora.server --demo` at the commit of this guide.

**Unit and integration tests.** `python -m unittest` over `test_bedrock_botocore`, `test_bedrock_control`, `test_bedrock_agent_control`, `test_bedrock_agent_runtime`, `test_bedrock_runtime`, `test_bedrock_guardrail`, `test_bedrock_http`, `test_bedrock_eventstream`, `test_bedrock_sigv4`: 129 tests, OK, 1 skipped. These use stub model and trainer servers in-process.

**Compatibility suite.** `PYTHON=<venv>/bin/python scripts/bedrock/run-compat.sh`, offline demo provider, temp database, developer access key plus admin bearer token: 74 operations, **73 PASS, 0 FAIL, 1 SKIP**.

| Script | PASS | FAIL | SKIP |
|---|---|---|---|
| `compat_runtime.py` | 20 | 0 | 0 |
| `compat_agent_runtime.py` | 12 | 0 | 0 |
| `compat_control.py` | 17 | 0 | 1 |
| `compat_agent_control.py` | 24 | 0 | 0 |

The one SKIP is `CreateModelCustomizationJob / Get / List`: the local run has no trainer (`NUVORA_TRAINER_URL`), and Nuvora answers `503 ServiceUnavailableException`. The unit tests cover that path with a stub trainer.

Two things the first runs of the scripts showed, handled in the scripts rather than the server:

- With `AWS_BEARER_TOKEN_BEDROCK` set, botocore silently signs with the bearer token and ignores access keys, so a naive "SigV4" check was really a bearer check. The scripts take the variable out of the environment and set the `Authorization` header explicitly.
- Guardrail writes with a developer access key answer `403 AccessDeniedException` (admin only). This is documented behaviour, and the suite asserts it.

**aws CLI (run by hand, not in CI).** With a developer access key: `bedrock list-foundation-models`, `bedrock-runtime converse` (HTTP 200, demo reply, usage), `bedrock-runtime count-tokens`, `bedrock-runtime invoke-model` (Nuvora chat body), `bedrock-agent list-knowledge-bases`, `bedrock-agent-runtime retrieve` (returned the demo field-guide passage). With `AWS_BEARER_TOKEN_BEDROCK` set to an admin token: `bedrock list-guardrails`, `bedrock create-guardrail` and `bedrock delete-guardrail`. A developer key on `bedrock create-guardrail` answered `AccessDeniedException`. `bedrock-agent list-agents` with only the bearer variable answered `NoCredentials` from the CLI itself (bearer tokens are not read for `bedrock-agent`). aws-cli 2.36.42 has no `converse-stream` command, so it was not run. Not run through the CLI: guardrail versions and tags, agent and alias management, ingestion jobs.

**Not verified.** Any real AWS account or endpoint; Terraform, CDK or CloudFormation providers; other SDK languages; a real model provider behind the Bedrock calls; a real trainer; Python versions other than 3.14 locally (CI runs the suite on 3.12).
