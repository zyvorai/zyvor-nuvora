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

Direct TLS:

```bash
python3 -m nuvora.server --host 0.0.0.0 --tls-cert /run/tls/cert.pem --tls-key /run/tls/key.pem --db /var/lib/nuvora/nuvora.db
```

`--demo` seeds once when no models exist. It never enables real model hosting. Avoid using the demo database for confidential production data.

## Container

```bash
docker build -f deploy/Dockerfile -t zyvor-nuvora:0.1.0 .
export NUVORA_ADMIN_PASSWORD='choose-your-own-strong-password'
docker compose -f deploy/compose.yaml up -d
```

The compose deployment binds loopback and expects a TLS reverse proxy before browser access. A direct browser request over HTTP cannot receive the Secure session cookie in this mode. For a simple local demo, use the Python quickstart; alternatively mount certificates and pass both TLS arguments to the container.

The image runs uid/gid 10001, drops capabilities in Compose/Helm, and writes only to its data volume. This image does not include optional boto3; create an extended image with the AWS extra if needed.

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

Either use a TLS ingress and preserve the external Host header, or serve TLS directly with `--set tls.existingSecret=YOUR_TLS_SECRET` and optionally `--set service.type=NodePort --set service.nodePort=30789`. Provide a real TLS secret. Keep one replica. The chart deliberately uses Recreate because the worker/database are not coordinated across processes. External provider secrets must be injected by your own Kubernetes Secret configuration; no secret plaintext belongs in Helm values.

## Backup and recovery

Use SQLite's online backup:

```bash
python3 - <<'PY'
import sqlite3
with sqlite3.connect('nuvora.db') as source, sqlite3.connect('nuvora-backup.db') as target:
    source.backup(target)
PY
```

Protect and encrypt backups: documents, prompts, job inputs, and memory are sensitive. To restore, stop the service, replace the database, and restart. Queued runs execute; runs previously marked running become interrupted and require review. Do not replay an interrupted run without considering whether the external request already completed.

## Evidence checks

Export Evidence from the console:

```bash
python3 scripts/verify-evidence.py nuvora-audit.json
```

Verification detects changed exported events. It cannot establish who produced the export or protect against a host administrator replacing the chain. Anchor chain tips externally or add a signing service before using this as independent audit proof.

## Limits

Chat timeout 45 seconds to providers, 1 MiB API body, up to 100 chat messages, max 8192 output tokens, up to 100 batch items, max 20 agent steps, four concurrent calls per user. The local worker executes serially. Inference rates are configured estimates. Embedding requests are not yet included in the chat budget/ledger.

No destructive production tools are registered. Adding one must include an exact action schema, scoped authorization, separate-human approval, idempotency, preconditions, outcome validation and a rollback procedure. Keep microVM integration is required before allowing untrusted browser/code tools.
