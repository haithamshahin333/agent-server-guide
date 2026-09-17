#!/usr/bin/env bash
# deploy.sh : install or upgrade the standalone Agent Server release with the Helm chart.
#
# The image repository and tag are passed with --set so the values files never need editing per
# build; everything else (secrets, sizing, split mode, ingress) lives in the values files.
# `--wait` makes Helm block until pods are Ready, so a bad image or a failed license check fails
# the pipeline instead of leaving a half-rolled release. `--atomic` would additionally roll back.
#
# Inputs (env): NAMESPACE, RELEASE, CHART, CHART_VERSION, VALUES_FILES, IMAGE_REPO, IMAGE_TAG,
#               REGISTRY, HELM_TIMEOUT
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

values_args=()
for f in $VALUES_FILES; do values_args+=(-f "$f"); done

log "helm upgrade -i $RELEASE $CHART --version $CHART_VERSION -n $NAMESPACE (image $HELM_IMAGE_REPO:$IMAGE_TAG)"
helm repo add langchain https://langchain-ai.github.io/helm >/dev/null 2>&1 || true
helm repo update >/dev/null

set +e
helm upgrade -i "$RELEASE" "$CHART" --version "$CHART_VERSION" \
  -n "$NAMESPACE" --create-namespace \
  "${values_args[@]}" \
  --set images.apiServerImage.repository="$HELM_IMAGE_REPO" \
  --set images.apiServerImage.tag="$IMAGE_TAG" \
  --wait --timeout "$HELM_TIMEOUT"
rc=$?
set -e

log "Release history"
helm -n "$NAMESPACE" history "$RELEASE" --max 5
log "Pods"
kubectl -n "$NAMESPACE" get pods -o wide

if [ $rc -ne 0 ]; then
  echo "ERROR: helm upgrade did not reach Ready within $HELM_TIMEOUT (exit $rc)." >&2
  echo "       Inspect: kubectl -n $NAMESPACE logs deploy/$RELEASE-langgraph-cloud-api-server --previous" >&2
  echo "       A 'License verification failed' log means LANGSMITH_API_KEY / LANGGRAPH_CLOUD_LICENSE_KEY" >&2
  echo "       are missing from the secret referenced by config.existingSecretName." >&2
  exit $rc
fi
