#!/usr/bin/env bash

echo ">>> Stopping all Flower containers..."

docker stop superexec-clientapp-1 superexec-clientapp-2 supernode-1 supernode-2 superexec-serverapp superlink 2>/dev/null || true

echo ">>> Removing docker network..."
docker network rm flower-network 2>/dev/null || true

echo "Done."