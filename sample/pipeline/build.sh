#!/usr/bin/env bash
# build.sh : regenerate the Dockerfile from langgraph.json and build the Agent Server image.
#
# Why regenerate every time: `langgraph dockerfile` renders the Dockerfile from langgraph.json
# (graphs, python_version, image_distro, dockerfile_lines ...). It does not update itself when the
# config changes, so the pipeline re-renders it and fails loudly if the committed copy drifted.
#
# Inputs (env): APP_DIR, DOCKERFILE, IMAGE_REPO, IMAGE_TAG, REGISTRY, PLATFORM, BASE_IMAGE
#
# BASE_IMAGE (optional): replace the rendered FROM line with this image reference. Use it for
# variants langgraph.json cannot express, such as the FIPS builds
# (e.g. BASE_IMAGE=langchain/langgraph-api:3.12-wolfi-fips) or an internal mirror. Keep the
# same Python version and distro family as langgraph.json so the rest of the Dockerfile still fits.
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

if [ ! -f "$APP_DIR/.dockerignore" ]; then
  echo "ERROR: $APP_DIR/.dockerignore is missing. The generated Dockerfile runs 'ADD . /deps/<name>'," >&2
  echo "       which would copy .env, .venv and .git into the image. Add a .dockerignore first (see module 07)." >&2
  exit 3
fi

log "Rendering Dockerfile from $APP_DIR/langgraph.json -> $DOCKERFILE"
tmp="$(mktemp -d)"
( cd "$APP_DIR" && uv run langgraph dockerfile "$tmp/Dockerfile" >/dev/null )
if [ -f "$DOCKERFILE" ] && ! diff -q "$DOCKERFILE" "$tmp/Dockerfile" >/dev/null; then
  echo "NOTE: committed Dockerfile differed from the rendered one; updating it." >&2
fi
mv "$tmp/Dockerfile" "$DOCKERFILE"
if [ -n "${BASE_IMAGE:-}" ]; then
  log "Overriding base image -> $BASE_IMAGE"
  sed -i "1s#^FROM .*#FROM $BASE_IMAGE#" "$DOCKERFILE"
fi
head -1 "$DOCKERFILE"

log "Building $IMAGE_REF"
platform_args=()
[ -n "$PLATFORM" ] && platform_args=(--platform "$PLATFORM")
docker build "${platform_args[@]}" -t "$IMAGE_REF" -f "$DOCKERFILE" "$APP_DIR"

log "Built image"
docker image ls "$IMAGE_REF" --format '{{.Repository}}:{{.Tag}}  {{.Size}}  {{.ID}}'
echo "IMAGE_REF=$IMAGE_REF"
