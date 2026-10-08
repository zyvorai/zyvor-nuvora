#!/usr/bin/env bash
# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
# Start a throwaway local Nuvora (offline demo provider, temp data dir, free port), run the four
# Bedrock compatibility scripts against it with boto3, print the combined table, tear it down.
#   PYTHON=/path/to/python scripts/bedrock/run-compat.sh      (needs boto3 in that interpreter)
set -uo pipefail
cd "$(dirname "$0")/../.."
PY="${PYTHON:-python3}"
"$PY" -c 'import boto3' 2>/dev/null || { echo "boto3 is not installed for $PY (pip install 'boto3>=1.35')" >&2; exit 2; }

TMP="$(mktemp -d)"
SERVER_PID=""
cleanup() { [ -n "$SERVER_PID" ] && kill "$SERVER_PID" 2>/dev/null && wait "$SERVER_PID" 2>/dev/null; rm -rf "$TMP"; }
trap cleanup EXIT INT TERM

PORT="$("$PY" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])')"
export NUVORA_SECRET_KEY="compat-suite-$(head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n')"
export NUVORA_ADMIN_PASSWORD="Compat-$(head -c 12 /dev/urandom | od -An -tx1 | tr -d ' \n')"
export NUVORA_CONNECTOR_HOSTS=127.0.0.1
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"

"$PY" -m nuvora.server --demo --host 127.0.0.1 --port "$PORT" --db "$TMP/nuvora.db" >"$TMP/server.log" 2>&1 &
SERVER_PID=$!
for _ in $(seq 1 100); do
  curl -fsS "http://127.0.0.1:$PORT/healthz" >/dev/null 2>&1 && break
  kill -0 "$SERVER_PID" 2>/dev/null || { echo "server exited:" >&2; cat "$TMP/server.log" >&2; exit 2; }
  sleep 0.1
done

eval "$("$PY" scripts/bedrock/_bootstrap.py "http://127.0.0.1:$PORT")" || { echo "bootstrap failed" >&2; cat "$TMP/server.log" >&2; exit 2; }
export NUVORA_COMPAT_JSON="$TMP/rows.jsonl"

status=0
for script in compat_runtime compat_agent_runtime compat_control compat_agent_control; do
  "$PY" "scripts/bedrock/$script.py" || status=1
done

"$PY" - "$NUVORA_COMPAT_JSON" <<'PYEOF'
import json, sys
rows = [json.loads(l) for l in open(sys.argv[1])]
print('\n== Combined: %d operations ==' % len(rows))
for status in ('PASS', 'FAIL', 'SKIP'):
    print('%s %d' % (status, sum(1 for r in rows if r[2] == status)))
for r in rows:
    if r[2] != 'PASS':
        print('  %-5s %s %s: %s' % (r[2], r[0], r[1], r[3][:160]))
PYEOF
exit "$status"
