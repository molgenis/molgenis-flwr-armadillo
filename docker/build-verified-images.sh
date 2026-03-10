#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

TAG="${1:-test}"
DOCKER_HUB_USER="timmyjc"
IMAGE_NAME="verified-supernode"
FULL_IMAGE="$DOCKER_HUB_USER/$IMAGE_NAME:$TAG"

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
