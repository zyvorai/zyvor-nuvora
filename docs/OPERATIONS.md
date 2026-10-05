# Operations

## Environment

| Variable | Purpose |
|---|---|
| `NUVORA_ADMIN_PASSWORD` | Initial default-tenant administrator password, 12–256 characters |
| `NUVORA_ALLOW_DEMO_PASSWORD` | Set to 1 to accept the demo password `Admin@321` for that first administrator only (labs; set by `deploy-remote.sh`) |
| `NUVORA_PROVIDER_HOSTS` | Exact comma-separated provider hostnames; default localhost,127.0.0.1 |
| `NUVORA_SECRET_*` | Operator-provided credentials referenced by model configuration |
| `NUVORA_BEHIND_TLS_PROXY` | Set to 1 only for a trusted HTTPS reverse proxy |
| `NUVORA_URL`, `NUVORA_TOKEN` | CLI base URL and scoped bearer token |
| `NUVORA_DATABASE_URL` | `postgresql://…` to use PostgreSQL instead of the `--db` SQLite file (needs the `postgres` extra) |
| `NUVORA_OIDC_ISSUER`, `NUVORA_OIDC_CLIENT_ID`, `NUVORA_OIDC_CLIENT_SECRET`, `NUVORA_OIDC_*` | Single sign-on; see the [SSO guide](https://zyvorai.github.io/zyvor-nuvora/docs/operate/sso) for the role map, tenant and identity claims |
| `NUVORA_NETRA_URL`, `NUVORA_ZYNTRA_URL`, `NUVORA_KEEP_URL` | Platform integrations; tokens in `NUVORA_SECRET_<SYSTEM>_TOKEN`; hosts must be on `NUVORA_PROVIDER_HOSTS`. `NUVORA_KEEP_IMAGE` picks the sandbox image |
| `NUVORA_CONNECTOR_HOSTS` | Exact comma-separated hostnames that web, S3 and Confluence connectors may reach. Empty (the default) refuses every connector |
| `NUVORA_TRAINER_URL` | Trainer service for fine-tuning and distillation jobs; token in `NUVORA_SECRET_TRAINER_TOKEN`; host must be on `NUVORA_PROVIDER_HOSTS` |
| `NUVORA_TRAINER_SERVING_URL`, `NUVORA_TRAINER_SERVING_KEY_ENV` | Where trained models are served when the trainer doesn't report a URL, and the `NUVORA_SECRET_*` name of its key |
| `NUVORA_ARTIFACT_TTL_DAYS` | How long generated images are kept, 1–365 days (default 7) |
| `NUVORA_OTEL_ENDPOINT` | OTLP/HTTP traces endpoint, such as `http://collector:4318/v1/traces`. Spans carry timings, models and costs, never prompt or answer text |

Optional Python extras: `pdf` (pypdf), `sso` (cryptography, for bearer JWTs), `postgres` (psycopg), `aws` (boto3), `ocr` (pytesseract and Pillow; also needs the `tesseract` binary, which the container image includes), or `all`. The core runs on the standard library; a missing extra returns 503 with an install hint.

Direct TLS:

```bash
python3 -m nuvora.server --host 0.0.0.0 --tls-cert /run/tls/cert.pem --tls-key /run/tls/key.pem --db /var/lib/nuvora/nuvora.db
```

`--demo` seeds once when no models exist. It never enables real model hosting. Avoid using the demo database for confidential production data.

## Container

```bash
docker build -f deploy/Dockerfile -t zyvor-nuvora:0.3.0 .
export NUVORA_ADMIN_PASSWORD='choose-your-own-strong-password'
docker compose -f deploy/compose.yaml up -d
```

The compose deployment binds loopback and expects a TLS reverse proxy before browser access. A direct browser request over HTTP cannot receive the Secure session cookie in this mode. For a simple local demo, use the Python quickstart; alternatively mount certificates and pass both TLS arguments to the container.

The image runs uid/gid 10001, drops capabilities in Compose/Helm, and writes only to its data volume. It installs every optional extra (`.[all]`), including boto3, pypdf, cryptography and psycopg. Tagged releases publish it as `ghcr.io/zyvorai/zyvor-nuvora:<version>`.

## Kubernetes

For a single k3s host, `./scripts/deploy-remote.sh HOST USER` does everything below for you: build on the host, TLS secret, Helm, rollout, health check. See [deploy.md](deploy.md).

Otherwise, build and push your image first. The example registry name is a target, not a published image.

```bash
kubectl create secret generic nuvora-admin --from-literal=password='choose-your-own-strong-password'
helm upgrade --install nuvora deploy/helm \
  --set image.repository=YOUR_REGISTRY/zyvor-nuvora \
  --set ingress.enabled=true \
  --set ingress.host=nuvora.example.com \
  --set ingress.tlsSecret=nuvora-tls
```

Either use a TLS ingress and preserve the external Host header, or serve TLS directly with `--set tls.existingSecret=YOUR_TLS_SECRET` and optionally `--set service.type=NodePort --set service.nodePort=30789`. Provide a real TLS secret. External provider secrets must be injected by your own Kubernetes Secret configuration; no secret plaintext belongs in Helm values.

With SQLite, keep one replica: the chart uses a PVC and `Recreate`. For several replicas, point `database.urlSecret` at a Secret whose `url` key holds a PostgreSQL URL. The chart then drops the PVC and rolls updates with `maxUnavailable: 0`. Rendering fails for `replicas > 1` without PostgreSQL. With SSO, it also fails unless `oidc.clientSecret` is set. SSO is configured under `oidc.*`.

```bash
kubectl create secret generic nuvora-db --from-literal=url='postgresql://nuvora:…@db:5432/nuvora?sslmode=require'
helm upgrade --install nuvora deploy/helm --set database.urlSecret=nuvora-db --set replicas=3
```

Move an existing SQLite database with `scripts/migrate-sqlite-to-postgres.py /data/nuvora.db` (stop Nuvora first). It copies in one transaction, keeps audit sequence numbers, verifies every tenant's chain, and refuses a non-empty target.

## Backup and recovery

On PostgreSQL, use `pg_dump`, WAL archiving or managed snapshots. On SQLite, use the online backup:

```bash
python3 - <<'PY'
import sqlite3
with sqlite3.connect('nuvora.db') as source, sqlite3.connect('nuvora-backup.db') as target:
    source.backup(target)
PY
```

Protect and encrypt backups: documents, prompts, job inputs, and memory are sensitive. To restore, stop the service, replace the database, and restart. Queued runs execute; runs previously marked running become interrupted and require review. With several replicas, a running job is interrupted only after its worker has missed heartbeats for 45 seconds. Do not replay an interrupted run without considering whether the external request already completed.

## Evidence checks

Export Evidence from the console:

```bash
python3 scripts/verify-evidence.py nuvora-audit.json
```

Verification detects changed exported events. It cannot establish who produced the export or protect against a host administrator replacing the chain. Anchor chain tips externally or add a signing service before using this as independent audit proof.

## People and keys

Administrators manage members in **Govern → Access**: create, change role, or remove. You can't change your own role or remove yourself, and the last administrator can't be demoted or removed. Demoting someone below developer revokes their service tokens.

Anyone can change their password from the account menu; that signs out their other sessions. Service tokens are created and revoked in **Govern → API keys** or with `POST`/`DELETE /api/tokens`. The secret is shown once. **Govern → Settings** shows administrators the effective transport, worker state, provider allow-list, policy, budget and limits.

## Limits

Chat timeout 45 seconds to providers (a streamed answer may run longer while data keeps arriving), 1 MiB API body (28 MiB for uploads, chat with images, extraction and datasets; 20 MB per file), up to 4 images per request at 7 MB each, up to 100 chat messages, max 8192 output tokens, up to 100 batch items, max 20 agent steps, four concurrent calls per user per replica. Each replica's worker executes serially. Inference rates are configured estimates. Embedding and rerank requests are not yet included in the chat budget/ledger.

No destructive production tools are registered. Adding one must include an exact action schema, scoped authorization, separate-human approval, idempotency, preconditions, outcome validation and a rollback procedure. Code runs only through Keep's `run_code`, after a different person approves the exact code, in a sandbox without network.
