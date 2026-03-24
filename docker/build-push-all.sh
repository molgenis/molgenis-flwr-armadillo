#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

DOCKER_HUB_USER="${DOCKER_HUB_USER:-timmyjc}"
PYTHON_AUTH_DIR="${PYTHON_AUTH_DIR:-$PROJECT_ROOT/../molgenis-python-auth}"

# Copy molgenis-python-auth into build context so Dockerfiles can COPY it
[ -d "$PYTHON_AUTH_DIR" ] || { echo "FAIL: molgenis-python-auth not found at $PYTHON_AUTH_DIR"; exit 1; }
cp -r "$PYTHON_AUTH_DIR" "$PROJECT_ROOT/molgenis-python-auth"
trap 'rm -rf "$PROJECT_ROOT/molgenis-python-auth"' EXIT

echo "Building verified-superlink..."
docker build --no-cache \
  -f "$SCRIPT_DIR/verified-superlink.Dockerfile" \
  -t "$DOCKER_HUB_USER/verified-superlink:test" \
  "$PROJECT_ROOT"

echo "Building superexec-data-test..."
docker build --no-cache \
  -f "$PROJECT_ROOT/examples/docker/superexec.Dockerfile" \
  -t "$DOCKER_HUB_USER/superexec-data-test:0.0.1" \
  "$PROJECT_ROOT"

echo "Pushing images..."
docker push "$DOCKER_HUB_USER/verified-superlink:test"
docker push "$DOCKER_HUB_USER/superexec-data-test:0.0.1"

echo "Done."