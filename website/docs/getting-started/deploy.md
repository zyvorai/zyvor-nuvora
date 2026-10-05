---
sidebar_position: 2
---

# Deploy to k3s

`scripts/deploy-remote.sh` deploys Nuvora to a single k3s host over SSH. It follows the same pattern as Zyvor Netra: the host builds its own image, so you don't need a registry.

```bash
./scripts/deploy-remote.sh 10.0.1.5 ubuntu     # HOST USER
./scripts/deploy-remote.sh ubuntu@10.0.1.5     # same thing
```

The host needs k3s, Helm, podman (or a working docker), and passwordless `sudo` for the image import. When the deploy finishes:
- Open `https://HOST:30789`. The certificate is self-signed and persists across redeploys.
- Sign in as `admin` in workspace `default` with the password the script printed. It's generated on the first deploy and stored in the `nuvora-system/nuvora-admin` secret.

## What it does

1. **Disk guard.** Warns at 80% root disk use and refuses to deploy at 95%.
2. **Sync.** rsyncs the tree to `~/.deployments/nuvora`.
3. **Build.** Runs `podman build -f deploy/Dockerfile` on the host, then `sudo k3s ctr images import`.
4. **Secrets.** Creates the `nuvora-system` namespace and these secrets:
   - `nuvora-admin`, holding the first administrator's password
   - `nuvora-tls`, a self-signed certificate whose SANs cover the host IPs; it's created once and reused, so pinned clients keep working
5. **Helm.** Runs `helm upgrade --install nuvora deploy/helm` with a NodePort service, direct TLS, the demo workspace, and your provider allow-list.
6. **Roll out.** Restarts the deployment and waits until it's ready. If kubelet garbage-collected the image, the script re-imports it.
7. **Verify.** Polls `/healthz` on the NodePort.

## Flags

| Flag | Effect |
|---|---|
| `--quick` | Sync and Helm only; reuses the image already on the host |
| `--verify-only` | Health-check the existing deployment and change nothing |
| `--dry-run` | Print the plan without touching the host |

## Environment

| Variable | Default | Purpose |
|---|---|---|
| `NUVORA_ADMIN_PASSWORD` | generated | First administrator's password (12+ characters) |
| `NUVORA_DEMO_PASSWORD` | `0` | Set `1` to use the demo login `Admin@321` (labs only) |
| `NUVORA_DEMO` | `1` | Seed the offline demo workspace |
| `NUVORA_NODE_PORT` | `30789` | HTTPS NodePort |
| `NUVORA_PROVIDER_HOSTS` | `localhost,127.0.0.1` | Exact model endpoint allow-list |
| `NUVORA_TLS_PERSIST` | `1` | Set `0` to serve plain HTTP behind your own TLS proxy |

:::warning The demo password is for labs
`Admin@321` is opt-in with `NUVORA_DEMO_PASSWORD=1`. It's accepted only for the bootstrap administrator, and only because the chart then sets `NUVORA_ALLOW_DEMO_PASSWORD=1`. Every other account still needs 12–256 characters.
:::

## Test the deployment

```bash
./scripts/deploy-remote.sh 10.0.1.5 ubuntu --verify-only
NUVORA_TEST_URL=https://10.0.1.5:30789 NUVORA_TEST_PASSWORD='YOUR_ADMIN_PASSWORD' \
  node scripts/browser-smoke.cjs
```

The browser smoke runs these checks with Playwright:
- signs in and opens every page
- runs an evaluation and follows it into Runs
- verifies the evidence chain
- checks light and dark mode at 1440px and 390px

## Without the script

The chart works on any cluster. Use one replica, because SQLite is single-process.

```bash
kubectl create secret generic nuvora-admin --from-literal=password='a-long-strong-password'
helm upgrade --install nuvora deploy/helm \
  --set image.repository=YOUR_REGISTRY/zyvor-nuvora \
  --set tls.existingSecret=YOUR_TLS_SECRET \
  --set service.type=NodePort --set service.nodePort=30789
```
