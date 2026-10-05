# Deploy to k3s

`scripts/deploy-remote.sh` deploys Nuvora to a single k3s host over SSH. It follows the same pattern as Zyvor Netra: the host builds its own image, so you don't need a registry.

```bash
./scripts/deploy-remote.sh 10.0.1.5 ubuntu     # HOST USER
./scripts/deploy-remote.sh ubuntu@10.0.1.5     # same thing
```

On success it prints `NUVORA ready` and `done — open https://10.0.1.5:30789 (sign in as admin)`. Sign in as `admin` in workspace `default`. On the first deploy the script generates a random administrator password and prints it once. It's stored in the `nuvora-system/nuvora-admin` secret, and later deploys reuse it.

The host needs k3s, Helm, podman (or a working docker), and passwordless `sudo` for the image import.

## What it does

1. **Disk guard.** Warns at 80% root disk use and refuses to deploy at 95%.
2. **Sync.** rsyncs the tree to `~/.deployments/nuvora`, excluding `node_modules`, release artifacts, and local databases.
3. **Build.** Runs `podman build -f deploy/Dockerfile` on the host, then `sudo k3s ctr images import`.
4. **Secrets.** Creates the `nuvora-system` namespace and these secrets:
   - `nuvora-admin`, holding the first administrator's password
   - `nuvora-tls`, a self-signed certificate whose SANs cover the host's IPs; it's created once and reused on every redeploy, so pinned clients keep working
5. **Helm.** Runs `helm upgrade --install nuvora deploy/helm`. The values set:
   - a NodePort service on 30789
   - direct TLS
   - the demo workspace
   - the provider allow-list
6. **Roll out.** Restarts the deployment and waits for the rollout to be ready (600 seconds by default). If kubelet garbage-collected the image, the script re-imports it.
7. **Verify.** Polls `/healthz` on the NodePort from the host. It also writes `~/.nuvora/env` and `~/.nuvora/tls.crt` there.

## Flags

| Flag | Effect |
|---|---|
| `--k3s` | Default profile: build on the host, import, Helm |
| `--quick` | Sync and Helm only; reuses the image already on the host |
| `--verify-only` | Health-check the existing deployment and change nothing |
| `--dry-run` | Print the plan without touching the host |

## Environment

| Variable | Default | Purpose |
|---|---|---|
| `NUVORA_ADMIN_PASSWORD` | generated | First administrator's password (12+ characters). It's only used when the database is first created. |
| `NUVORA_DEMO_PASSWORD` | `0` | Set `1` to use the demo login `Admin@321` instead (labs only) |
| `NUVORA_DEMO` | `1` | Seed the offline demo workspace |
| `NUVORA_NODE_PORT` | `30789` | HTTPS NodePort |
| `NUVORA_PROVIDER_HOSTS` | `localhost,127.0.0.1` | Exact model endpoint allow-list |
| `NUVORA_REMOTE_SUBDIR` | `.deployments/nuvora` | Checkout location under the remote `$HOME` |
| `NUVORA_TLS_PERSIST` | `1` | Set `0` to serve plain HTTP and terminate TLS elsewhere |
| `NUVORA_DEPLOY_WARN_DISK_PCT` / `NUVORA_DEPLOY_MAX_DISK_PCT` | `80` / `95` | Disk guard thresholds |
| `NUVORA_DEPLOY_READY_TIMEOUT` | `600` | Rollout wait in seconds |

## The demo password

`Admin@321` matches Netra's demo login. It's opt-in: run the deploy with `NUVORA_DEMO_PASSWORD=1`. Two settings then work together:
- The script sets the chart's `allowDemoPassword`, which sets `NUVORA_ALLOW_DEMO_PASSWORD=1` in the pod.
- With that variable set, the server accepts exactly this one shorter password for the bootstrap administrator.

Every other password, including users created later, still needs 12–256 characters. To rotate the generated password, sign in and add a new administrator in **Access**, or set `NUVORA_ADMIN_PASSWORD` before a fresh first deploy.

## Checks

```bash
./scripts/deploy-remote.sh 10.0.1.5 ubuntu --verify-only
NUVORA_TEST_URL=https://10.0.1.5:30789 NUVORA_TEST_PASSWORD='YOUR_ADMIN_PASSWORD' node scripts/browser-smoke.cjs
```

CI runs `helm lint`, `helm template`, `shellcheck`, and `scripts/ci-deploy-guards.sh` on every push.

## Helm values

The chart can also be used without the script. These are the values the script relies on:

```yaml
service:
  type: NodePort          # ClusterIP by default
  port: 8789
  nodePort: "30789"
tls:
  existingSecret: nuvora-tls   # any kubernetes.io/tls Secret; empty = plain HTTP behind a proxy
demo: true
allowDemoPassword: false
providerHosts: "localhost,127.0.0.1"
```

With SQLite, keep one replica; the chart uses `Recreate`. For several replicas, set `database.urlSecret` to a Secret holding a PostgreSQL URL (see [OPERATIONS.md](OPERATIONS.md)).
