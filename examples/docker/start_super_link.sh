#!/usr/bin/env bash
set -euo pipefail

CLIENT_IMAGE="$1"
echo ">>> Starting superlink..."
docker run -d --rm \
  -p 9091:9091 \
  -p 9092:9092 \
  -p 9093:9093 \
  --name superlink \
  flwr/superlink:1.23.0 \
  --insecure \
  --isolation process

echo ">>> Starting example app (superexec-serverapp)..."
docker run -d --rm \
  --name superexec-serverapp \
  "$CLIENT_IMAGE" \
  --insecure \
  --plugin-type serverapp \
  --appio-api-address host.docker.internal:9091

echo "All containers started."
echo
echo "Use 'docker ps' to check them, and 'docker logs -f <container-name>' to see logs."
