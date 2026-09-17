#!/usr/bin/env bash
# smoke.sh : prove the deployed server answers and can execute a run.
#
# Port-forwards the api-server Service (no ingress needed), then checks /ok, /info and one
# stateless `POST /runs/wait` against the LLM-free `echo` graph. In a real pipeline point
# BASE_URL at the ingress hostname and skip the port-forward.
#
# Inputs (env): NAMESPACE, RELEASE, BASE_URL (optional), LOCAL_PORT
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
LOCAL_PORT="${LOCAL_PORT:-8080}"
SVC="svc/$RELEASE-langgraph-cloud-api-server"
pf_pid=""

cleanup() { [ -n "$pf_pid" ] && kill "$pf_pid" 2>/dev/null || true; }
trap cleanup EXIT

if [ -z "${BASE_URL:-}" ]; then
  log "Port-forwarding $SVC -> localhost:$LOCAL_PORT"
  kubectl -n "$NAMESPACE" port-forward "$SVC" "$LOCAL_PORT:80" >/dev/null 2>&1 &
  pf_pid=$!
  sleep 3
  BASE_URL="http://127.0.0.1:$LOCAL_PORT"
fi

fail() { echo "SMOKE FAILED: $*" >&2; exit 1; }

log "GET $BASE_URL/ok"
ok="$(curl -s -m 10 "$BASE_URL/ok" || true)"
echo "${ok:-<no response>}"
[ "$ok" = '{"ok":true}' ] || fail "/ok did not return {\"ok\":true}. Pods not Ready? Check: kubectl -n $NAMESPACE get pods"

log "GET $BASE_URL/info"
curl -s -m 10 "$BASE_URL/info" | python3 -c 'import sys,json; d=json.load(sys.stdin); print("version", d["version"], "host.kind", d["host"]["kind"])' \
  || fail "/info unreadable"

log "POST $BASE_URL/runs/wait (assistant_id=echo)"
resp="$(curl -s -m 60 -X POST "$BASE_URL/runs/wait" -H 'Content-Type: application/json' \
  -d '{"assistant_id":"echo","input":{"messages":[{"role":"user","content":"smoke test"}]}}')"
echo "$resp" | python3 -c 'import sys,json; d=json.load(sys.stdin); m=d["messages"][-1]["content"]; print("reply:", m); sys.exit(0 if m=="echo: smoke test" else 1)' \
  || fail "run did not return the expected reply: $resp"

log "SMOKE PASSED"
