#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

TAG="${1:-test}"
DOCKER_HUB_USER="timmyjc"
IMAGE_NAME="verified-supernode"
FULL_IMAGE="$DOCKER_HUB_USER/$IMAGE_NAME:$TAG"
PYTHON_AUTH_DIR="${PYTHON_AUTH_DIR:-$PROJECT_ROOT/../molgenis-python-auth}"

# Copy molgenis-python-auth into build context so Dockerfile can COPY it
[ -d "$PYTHON_AUTH_DIR" ] || { echo "FAIL: molgenis-python-auth not found at $PYTHON_AUTH_DIR"; exit 1; }
cp -r "$PYTHON_AUTH_DIR" "$PROJECT_ROOT/molgenis-python-auth"
trap 'rm -rf "$PROJECT_ROOT/molgenis-python-auth"' EXIT

# Check if image already exists on Docker Hub
if docker manifest inspect "$FULL_IMAGE" >/dev/null 2>&1; then
  echo "Image $FULL_IMAGE already exists on Docker Hub. Skipping build and push."
  exit 0
fi

echo "Building $FULL_IMAGE ..."
docker build \
  -f "$SCRIPT_DIR/verified-supernode.Dockerfile" \
  -t "$FULL_IMAGE" \
  "$PROJECT_ROOT"

echo "Pushing $FULL_IMAGE to Docker Hub..."
docker push "$FULL_IMAGE"

echo "Done. Image available at: $FULL_IMAGE"
