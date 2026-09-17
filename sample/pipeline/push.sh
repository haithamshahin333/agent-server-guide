#!/usr/bin/env bash
# push.sh : publish the image where the cluster can pull it.
#
# Real environments: docker push to $REGISTRY (authenticate before calling this script, e.g.
# `docker login` or your cloud CLI's registry login).
# Local kind clusters have no registry, so when KIND_CLUSTER is set the script side-loads the
# image with `kind load docker-image` instead. Treat that as the local stand-in for a push.
#
# Inputs (env): IMAGE_REPO, IMAGE_TAG, REGISTRY, KIND_CLUSTER
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

if [ -n "$KIND_CLUSTER" ]; then
  log "Loading $IMAGE_REF into kind cluster '$KIND_CLUSTER' (local substitute for a registry push)"
  kind load docker-image "$IMAGE_REF" --name "$KIND_CLUSTER"
elif [ -n "$REGISTRY" ]; then
  log "Pushing $IMAGE_REF"
  docker push "$IMAGE_REF"
else
  echo "ERROR: set REGISTRY (docker push) or KIND_CLUSTER (kind load)." >&2
  exit 2
fi
echo "IMAGE_REF=$IMAGE_REF"
