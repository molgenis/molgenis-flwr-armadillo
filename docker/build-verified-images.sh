#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

TAG="${1:-1.23.0}"

echo "Building verified-supernode:${TAG} ..."
docker build \
  -f "$SCRIPT_DIR/verified-supernode.Dockerfile" \
  -t "molgenis/verified-supernode:${TAG}" \
  "$PROJECT_ROOT"

echo "Done. Image:"
echo "  molgenis/verified-supernode:${TAG}"
