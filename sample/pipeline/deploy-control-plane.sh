#!/usr/bin/env bash
# deploy-control-plane.sh : create or update a LangSmith Deployment through the self-hosted control
# plane API, pointing it at the image your pipeline pushed and at the managed Postgres and Redis
# whose URIs provision-datastores.sh stored in a Kubernetes Secret.
#
# This is the control-plane counterpart of deploy.sh (which does `helm upgrade` for the standalone
# path). Same image, same pipeline; only the last step differs.
#
# Inputs (environment variables):
#   CONTROL_PLANE_HOST   self-hosted: https://<your-langsmith-host>/api-host
#   LANGSMITH_API_KEY    API key for the workspace (sent as X-Api-Key)
#   WORKSPACE_ID         workspace ID (sent as X-Tenant-Id)
#   LISTENER_COMPUTE_ID  the listener's Compute ID as shown in the UI (resolved to listener_id)
#   K8S_NAMESPACE        target namespace; must be one the listener is configured for
#   DEPLOYMENT_NAME      deployment name; an existing deployment with this name gets a new revision
#   IMAGE_URI            e.g. registry.example.internal/platform/my-agent:1.4.0
#   DATASTORE_SECRET     Kubernetes Secret in K8S_NAMESPACE holding keys postgres_uri and redis_uri
#   APP_SECRETS          optional, comma-separated NAME=VALUE pairs sent as inline secrets
#   MIN_SCALE / MAX_SCALE / CPU / MEMORY_MB / QUEUE_MIN_SCALE / QUEUE_MAX_SCALE  optional sizing
#   SERVICE_ACCOUNT      optional, pre-existing ServiceAccount in K8S_NAMESPACE (for IAM auth)
#   POLL_TIMEOUT_SECS    default 900
#
# API reference: https://docs.langchain.com/langsmith/api-ref-control-plane and
# https://docs.langchain.com/api-reference/deployments-v2/create-deployment
#
# NOT EXERCISED while writing the guide (no self-hosted control plane was available). The request
# shapes follow the published OpenAPI schema for `external_docker` deployments.
set -euo pipefail

for v in CONTROL_PLANE_HOST LANGSMITH_API_KEY WORKSPACE_ID LISTENER_COMPUTE_ID K8S_NAMESPACE DEPLOYMENT_NAME IMAGE_URI DATASTORE_SECRET; do
  [ -n "${!v:-}" ] || { echo "ERROR: set $v" >&2; exit 2; }
done
POLL_TIMEOUT_SECS="${POLL_TIMEOUT_SECS:-900}"

api() { # api METHOD PATH [JSON_BODY]
  local method="$1" path="$2" body="${3:-}"
  if [ -n "$body" ]; then
    curl -sS -f -X "$method" "${CONTROL_PLANE_HOST}${path}" \
      -H "X-Api-Key: ${LANGSMITH_API_KEY}" -H "X-Tenant-Id: ${WORKSPACE_ID}" \
      -H "Content-Type: application/json" --data "$body"
  else
    curl -sS -f -X "$method" "${CONTROL_PLANE_HOST}${path}" \
      -H "X-Api-Key: ${LANGSMITH_API_KEY}" -H "X-Tenant-Id: ${WORKSPACE_ID}"
  fi
}

echo "==> Resolving listener with compute_id=${LISTENER_COMPUTE_ID}"
LISTENER_ID="$(api GET "/v2/listeners?limit=100" | python3 -c '
import sys, json, os
want = os.environ["LISTENER_COMPUTE_ID"]; ns = os.environ["K8S_NAMESPACE"]
for l in json.load(sys.stdin)["resources"]:
    if l["compute_id"] == want:
        nss = (l.get("compute_config") or {}).get("k8s_namespaces") or []
        if nss and ns not in nss:
            sys.exit(f"listener {want} is not configured for namespace {ns}; it allows {nss}")
        print(l["id"]); break
else:
    sys.exit(f"no listener with compute_id {want}")
')"
echo "    listener_id=${LISTENER_ID}"

# Build the JSON body once; POST and PATCH share it.
BODY="$(python3 - <<'PY'
import json, os
env = os.environ
secrets = []
for pair in filter(None, env.get("APP_SECRETS", "").split(",")):
    k, _, v = pair.partition("=")
    secrets.append({"name": k, "value": v})
spec = {}
for key, var, cast in [("min_scale","MIN_SCALE",int),("max_scale","MAX_SCALE",int),("cpu","CPU",float),
                       ("memory_mb","MEMORY_MB",int),("queue_min_scale","QUEUE_MIN_SCALE",int),
                       ("queue_max_scale","QUEUE_MAX_SCALE",int)]:
    if env.get(var): spec[key] = cast(env[var])
if env.get("SERVICE_ACCOUNT"): spec["service_account_name"] = env["SERVICE_ACCOUNT"]
body = {
    "name": env["DEPLOYMENT_NAME"],
    "source": "external_docker",
    "source_config": {
        "listener_id": env["LISTENER_ID"],
        "listener_config": {"k8s_namespace": env["K8S_NAMESPACE"]},
        "resource_spec": spec or None,
    },
    "source_revision_config": {"image_uri": env["IMAGE_URI"]},
    "secrets": secrets,
    # The managed data stores: values stay in the cluster Secret, never in this request.
    "secret_references": [
        {"name": "POSTGRES_URI_CUSTOM", "secret_name": env["DATASTORE_SECRET"], "secret_key": "postgres_uri"},
        {"name": "REDIS_URI_CUSTOM",    "secret_name": env["DATASTORE_SECRET"], "secret_key": "redis_uri"},
    ],
}
print(json.dumps(body))
PY
)"
export LISTENER_ID

echo "==> Looking for an existing deployment named ${DEPLOYMENT_NAME}"
DEPLOYMENT_ID="$(api GET "/v2/deployments?limit=100" | python3 -c '
import sys, json, os
for d in json.load(sys.stdin)["resources"]:
    if d["name"] == os.environ["DEPLOYMENT_NAME"]:
        print(d["id"]); break
')"

if [ -z "$DEPLOYMENT_ID" ]; then
  echo "==> POST /v2/deployments (create)"
  RESP="$(api POST "/v2/deployments" "$BODY")"
else
  echo "==> PATCH /v2/deployments/${DEPLOYMENT_ID} (new revision with image ${IMAGE_URI})"
  # listener_id and k8s_namespace cannot change after creation; send only what a revision needs.
  PATCH_BODY="$(echo "$BODY" | python3 -c 'import sys,json; b=json.load(sys.stdin); b.pop("source",None); b["source_config"].pop("listener_id",None); b["source_config"].pop("listener_config",None); print(json.dumps(b))')"
  RESP="$(api PATCH "/v2/deployments/${DEPLOYMENT_ID}" "$PATCH_BODY")"
fi
read -r DEPLOYMENT_ID REVISION_ID <<<"$(echo "$RESP" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d["id"], d["latest_revision_id"])')"
echo "    deployment_id=${DEPLOYMENT_ID} revision_id=${REVISION_ID}"

echo "==> Polling revision status (timeout ${POLL_TIMEOUT_SECS}s)"
deadline=$(( $(date +%s) + POLL_TIMEOUT_SECS ))
while :; do
  read -r STATUS MSG <<<"$(api GET "/v2/deployments/${DEPLOYMENT_ID}/revisions/${REVISION_ID}" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d["status"], (d.get("status_message") or "").replace("\n"," ")[:200])')"
  echo "    $(date +%H:%M:%S) ${STATUS} ${MSG}"
  case "$STATUS" in
    DEPLOYED) echo "==> DEPLOYED"; exit 0 ;;
    CREATE_FAILED|BUILD_FAILED|DEPLOY_FAILED|INTERRUPTED) echo "ERROR: revision ended in ${STATUS}" >&2; exit 1 ;;
  esac
  [ "$(date +%s)" -lt "$deadline" ] || { echo "ERROR: timed out waiting for DEPLOYED (last status ${STATUS})" >&2; exit 1; }
  sleep 15
done
