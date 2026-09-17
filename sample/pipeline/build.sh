#!/usr/bin/env bash
# build.sh : regenerate the Dockerfile from langgraph.json and build the Agent Server image.
#
# Why regenerate every time: `langgraph dockerfile` renders the Dockerfile from langgraph.json
# (graphs, python_version, image_distro, dockerfile_lines ...). It does not update itself when the
# config changes, so the pipeline re-renders it and fails loudly if the committed copy drifted.
#
# Inputs (env): APP_DIR, DOCKERFILE, IMAGE_REPO, IMAGE_TAG, REGISTRY, PLATFORM
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

log "Rendering Dockerfile from $APP_DIR/langgraph.json -> $DOCKERFILE"
tmp="$(mktemp -d)"
( cd "$APP_DIR" && uv run langgraph dockerfile "$tmp/Dockerfile" >/dev/null )
if [ -f "$DOCKERFILE" ] && ! diff -q "$DOCKERFILE" "$tmp/Dockerfile" >/dev/null; then
  echo "NOTE: committed Dockerfile differed from the rendered one; updating it." >&2
fi
mv "$tmp/Dockerfile" "$DOCKERFILE"

log "Building $IMAGE_REF"
platform_args=()
[ -n "$PLATFORM" ] && platform_args=(--platform "$PLATFORM")
docker build "${platform_args[@]}" -t "$IMAGE_REF" -f "$DOCKERFILE" "$APP_DIR"

log "Built image"
docker image ls "$IMAGE_REF" --format '{{.Repository}}:{{.Tag}}  {{.Size}}  {{.ID}}'
echo "IMAGE_REF=$IMAGE_REF"
