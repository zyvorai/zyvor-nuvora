#!/usr/bin/env bash
# Nuvora — remote deploy (SSH + rsync + podman build + k3s import + Helm)
#
# Profiles:
#   default / --k3s   Build the image on the host, import it into k3s, then Helm
#   --quick           Sync + Helm only (the image must already be on the host)
#
# Usage:
#   ./scripts/deploy-remote.sh user@10.0.1.5
#   ./scripts/deploy-remote.sh 10.0.1.5 user
#   ./scripts/deploy-remote.sh user@10.0.1.5 --verify-only
#   ./scripts/deploy-remote.sh user@10.0.1.5 --dry-run
#
# Environment:
#   NUVORA_ADMIN_PASSWORD   first administrator's password (default Admin@321, the
#                           Netra-style demo login; anything else needs 12+ chars).
#                           Only used when the workspace database is first created.
#   NUVORA_DEMO             seed the offline demo workspace (default 1)
#   NUVORA_NODE_PORT        HTTPS NodePort (default 30789)
#   NUVORA_PROVIDER_HOSTS   model endpoint allowlist (default localhost,127.0.0.1)
#   NUVORA_REMOTE_SUBDIR    checkout location relative to the remote $HOME
#                           (default .deployments/nuvora)
#   NUVORA_TLS_PERSIST=0    let the chart serve plain HTTP instead of the persistent
#                           self-signed nuvora-tls certificate
#
# Deploy guards (scripts/lib/deploy-guards.sh): warns at NUVORA_DEPLOY_WARN_DISK_PCT
# (80), refuses at NUVORA_DEPLOY_MAX_DISK_PCT (95), re-imports an image kubelet
# garbage-collected, and waits for the rollout to complete
# (NUVORA_DEPLOY_READY_TIMEOUT, default 600 s) instead of trusting helm.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

VERSION="0.1.0"
IMAGE="ghcr.io/zyvorai/zyvor-nuvora:${VERSION}"
NAMESPACE="nuvora-system"
PROFILE="k3s"
DRY_RUN=false
VERIFY_ONLY=false
TARGET=""
POSITIONAL=()
SSH_OPTS=(-o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30)

usage() {
  sed -n '2,29p' "$0" | sed 's/^# \{0,1\}//'
  exit 0
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage ;;
    --k3s) PROFILE="k3s"; shift ;;
    --quick) PROFILE="quick"; shift ;;
    --dry-run) DRY_RUN=true; shift ;;
    --verify-only) VERIFY_ONLY=true; shift ;;
    -*)
      echo "unknown flag: $1" >&2
      exit 2
      ;;
    *)
      POSITIONAL+=("$1")
      shift
      ;;
  esac
done

if [[ ${#POSITIONAL[@]} -eq 1 ]]; then
  TARGET="${POSITIONAL[0]}"
elif [[ ${#POSITIONAL[@]} -eq 2 ]]; then
  # ./scripts/deploy-remote.sh HOST USER
  if [[ "${POSITIONAL[0]}" == *@* ]]; then
    TARGET="${POSITIONAL[0]}"
  elif [[ "${POSITIONAL[1]}" == *@* ]]; then
    TARGET="${POSITIONAL[1]}"
  else
    TARGET="${POSITIONAL[1]}@${POSITIONAL[0]}"
  fi
fi

if [[ -z "${TARGET}" ]]; then
  echo "usage: $0 user@host [--k3s|--quick] [--dry-run|--verify-only]" >&2
  echo "   or: $0 HOST USER" >&2
  exit 2
fi

HOST="${TARGET#*@}"
ADMIN_PASSWORD_LOCAL="${NUVORA_ADMIN_PASSWORD:-Admin@321}"
DEMO_LOCAL="${NUVORA_DEMO:-1}"
NODE_PORT_LOCAL="${NUVORA_NODE_PORT:-30789}"
PROVIDER_HOSTS_LOCAL="${NUVORA_PROVIDER_HOSTS:-localhost,127.0.0.1}"
TLS_PERSIST_LOCAL="${NUVORA_TLS_PERSIST:-1}"
SCHEME="https"
[[ "$TLS_PERSIST_LOCAL" == "0" ]] && SCHEME="http"

log() { printf '[nuvora-deploy] %s\n' "$*"; }
ssh_host() { ssh "${SSH_OPTS[@]}" "$TARGET" "$@"; }

if (( ${#ADMIN_PASSWORD_LOCAL} < 12 )) && [[ "$ADMIN_PASSWORD_LOCAL" != "Admin@321" ]]; then
  echo "NUVORA_ADMIN_PASSWORD must contain 12+ characters (or be the demo password Admin@321)" >&2
  exit 2
fi

if $DRY_RUN; then
  REMOTE_HOME="\$HOME"
else
  REMOTE_HOME="$(ssh_host 'printf %s "$HOME"')"
fi
REMOTE_DIR="${REMOTE_HOME}/${NUVORA_REMOTE_SUBDIR:-.deployments/nuvora}"

if $VERIFY_ONLY; then
  ssh_host "NODE_PORT=${NODE_PORT_LOCAL} SCHEME=${SCHEME} bash -s" <<'EOF'
set -euo pipefail
export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/nuvora-k3s.yaml}"
if [[ ! -r "${KUBECONFIG}" ]]; then
  mkdir -p "$HOME/.kube"
  sudo cat /etc/rancher/k3s/k3s.yaml > "$HOME/.kube/nuvora-k3s.yaml"
  chmod 600 "$HOME/.kube/nuvora-k3s.yaml"
fi
kubectl -n nuvora-system get deploy,svc,pods,pvc
curl -skf "${SCHEME}://127.0.0.1:${NODE_PORT}/healthz"
echo
EOF
  exit 0
fi

log "sync → ${TARGET}:${REMOTE_DIR}"
if ! $DRY_RUN; then
  ssh_host "mkdir -p ${REMOTE_DIR}"
  rsync -az --delete \
    --exclude '.git' --exclude 'web/node_modules' --exclude 'web/dist' \
    --exclude 'website/node_modules' --exclude 'website/build' --exclude 'website/.docusaurus' \
    --exclude 'node_modules' --exclude 'release' --exclude 'docs/screenshots' \
    --exclude '*.db' --exclude '*.db-*' --exclude '__pycache__' --exclude '.DS_Store' --exclude '.cursor' \
    "${ROOT}/" "${TARGET}:${REMOTE_DIR}/"
fi

remote_script=$(cat <<EOF
set -euo pipefail
cd ${REMOTE_DIR}
export PATH="/usr/local/bin:/usr/bin:\$PATH"
PROFILE="${PROFILE}"
IMAGE="${IMAGE}"
NAMESPACE="${NAMESPACE}"
NODE_PORT="${NODE_PORT_LOCAL}"
DEMO="${DEMO_LOCAL}"
PROVIDER_HOSTS="${PROVIDER_HOSTS_LOCAL}"
TLS_PERSIST="${TLS_PERSIST_LOCAL}"
SCHEME="${SCHEME}"
ADMIN_PASSWORD='${ADMIN_PASSWORD_LOCAL//\'/\'\\\'\'}'

mkdir -p "\$HOME/.kube"
if [[ ! -r "\$HOME/.kube/nuvora-k3s.yaml" ]] || [[ /etc/rancher/k3s/k3s.yaml -nt "\$HOME/.kube/nuvora-k3s.yaml" ]]; then
  sudo cat /etc/rancher/k3s/k3s.yaml > "\$HOME/.kube/nuvora-k3s.yaml"
  chmod 600 "\$HOME/.kube/nuvora-k3s.yaml"
fi
export KUBECONFIG="\$HOME/.kube/nuvora-k3s.yaml"

export DEPLOY_NAMESPACE="\$NAMESPACE"
source scripts/lib/deploy-guards.sh
deploy_disk_guard /

runtime=""
if command -v podman >/dev/null 2>&1; then
  runtime=podman
elif command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  runtime=docker
fi

if [[ "\$PROFILE" != "quick" ]]; then
  if [[ -z "\$runtime" ]]; then
    echo "podman or working docker required to build the Nuvora image" >&2
    exit 1
  fi
  echo "Building \$IMAGE with \$runtime (console + Python runtime)..."
  \$runtime build -f deploy/Dockerfile -t "\$IMAGE" .
  deploy_import_image "\$IMAGE"
fi

HOST_IP="\$(hostname -I | awk '{print \$1}')"
kubectl create namespace "\$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f - >/dev/null

# First administrator. The server reads this only when the database is created.
kubectl -n "\$NAMESPACE" create secret generic nuvora-admin --from-literal=password="\$ADMIN_PASSWORD" \
  --dry-run=client -o yaml | kubectl apply -f - >/dev/null

# One self-signed certificate across restarts so clients can pin it.
mkdir -p "\$HOME/.nuvora"
TLS_SET=()
if [[ "\$TLS_PERSIST" != "0" ]]; then
  if ! kubectl -n "\$NAMESPACE" get secret nuvora-tls >/dev/null 2>&1; then
    tls_dir="\$(mktemp -d)"
    openssl req -x509 -nodes -days 3650 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 \
      -keyout "\$tls_dir/tls.key" -out "\$tls_dir/tls.crt" -subj "/CN=nuvora/O=Zyvor AI Labs" \
      -addext "subjectAltName=DNS:nuvora,DNS:nuvora.\$NAMESPACE.svc,DNS:localhost,IP:127.0.0.1,IP:\$HOST_IP,IP:${HOST}" 2>/dev/null \
    || openssl req -x509 -nodes -days 3650 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 \
      -keyout "\$tls_dir/tls.key" -out "\$tls_dir/tls.crt" -subj "/CN=nuvora/O=Zyvor AI Labs" \
      -addext "subjectAltName=DNS:nuvora,DNS:nuvora.\$NAMESPACE.svc,DNS:localhost,IP:127.0.0.1,IP:\$HOST_IP" 2>/dev/null
    kubectl -n "\$NAMESPACE" create secret tls nuvora-tls --cert="\$tls_dir/tls.crt" --key="\$tls_dir/tls.key" >/dev/null
    rm -rf "\$tls_dir"
  fi
  kubectl -n "\$NAMESPACE" get secret nuvora-tls -o jsonpath='{.data.tls\.crt}' | base64 -d > "\$HOME/.nuvora/tls.crt"
  TLS_SET=(--set tls.existingSecret=nuvora-tls)
fi

DEMO_SET=(--set demo=false)
[[ "\$DEMO" == "1" ]] && DEMO_SET=(--set demo=true)
PASSWORD_SET=(--set allowDemoPassword=false)
[[ "\$ADMIN_PASSWORD" == "Admin@321" ]] && PASSWORD_SET=(--set allowDemoPassword=true)

deploy_ensure_image "\$IMAGE"

helm upgrade --install nuvora ./deploy/helm \
  --namespace "\$NAMESPACE" --create-namespace \
  "\${TLS_SET[@]}" \
  "\${DEMO_SET[@]}" \
  "\${PASSWORD_SET[@]}" \
  --set image.repository="\${IMAGE%:*}" \
  --set image.tag="\${IMAGE##*:}" \
  --set image.pullPolicy=IfNotPresent \
  --set-string providerHosts="\${PROVIDER_HOSTS//,/\\\\,}" \
  --set service.type=NodePort \
  --set service.port=8789 \
  --set service.nodePort="\$NODE_PORT" \
  --wait --timeout 300s

# The tag is fixed, so the pod template does not change between builds and helm has
# nothing to roll out. Restart so the freshly imported image is what runs.
deploy_ensure_image "\$IMAGE"
kubectl -n "\$NAMESPACE" rollout restart deployment/nuvora
deploy_wait_ready deployment/nuvora "app.kubernetes.io/name=nuvora" "\$IMAGE"

cat > "\$HOME/.nuvora/env" <<ENVEOF
# Written by deploy-remote.sh — read by nuvoractl and the browser smoke.
NUVORA_URL=\${SCHEME}://\${HOST_IP}:\${NODE_PORT}
NUVORA_TLS_INSECURE=true
ENVEOF
chmod 600 "\$HOME/.nuvora/"*

for _ in \$(seq 1 30); do
  if curl -skf "\${SCHEME}://127.0.0.1:\${NODE_PORT}/healthz"; then
    echo
    echo "NUVORA_URL=\${SCHEME}://\${HOST_IP}:\${NODE_PORT}"
    echo "NUVORA ready (k3s, \${SCHEME^^} NodePort \${NODE_PORT})"
    exit 0
  fi
  sleep 2
done
echo "Nuvora did not answer /healthz on NodePort \${NODE_PORT}" >&2
kubectl -n "\$NAMESPACE" get pods -o wide >&2
kubectl -n "\$NAMESPACE" logs deployment/nuvora --tail=50 >&2 || true
exit 1
EOF
)

if $DRY_RUN; then
  log "dry-run remote script:"
  echo "$remote_script"
  exit 0
fi

ssh_host 'bash -s' <<<"$remote_script"
log "done — open ${SCHEME}://${HOST}:${NODE_PORT_LOCAL} (sign in as admin)"
