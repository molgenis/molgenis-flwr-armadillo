#!/usr/bin/env bash
set -euo pipefail

NETWORK_NAME="flower-node2-network"
CLIENT_IMAGE="$1"

echo ">>> Ensuring docker network '$NETWORK_NAME' exists..."
if ! docker network inspect "$NETWORK_NAME" >/dev/null 2>&1; then
  docker network create --driver bridge "$NETWORK_NAME"
fi

echo ">>> Starting first supernode..."
docker run -d --rm \
  -p 9094:9094 \
  --network "$NETWORK_NAME" \
  --name supernode-1 \
  flwr/supernode:1.23.0 \
  --insecure \
  --superlink host.docker.internal:9092 \
  --node-config "partition-id=1 num-partitions=2 node-name=barcelona" \
  --clientappio-api-address 0.0.0.0:9094 \
  --isolation process

echo ">>> Starting second supernode..."
docker run -d --rm \
  -p 9095:9095 \
  --network "$NETWORK_NAME" \
  --name supernode-2 \
  flwr/supernode:1.23.0 \
  --insecure \
  --superlink host.docker.internal:9092 \
  --node-config "partition-id=1 num-partitions=2 node-name=groningen" \
  --clientappio-api-address 0.0.0.0:9095 \
  --isolation process

echo ">>> Starting the client app for supernode 1 (clientapp)..."
docker run -d --rm \
  --network "$NETWORK_NAME" \
  --name superexec-clientapp-1 \
  "$CLIENT_IMAGE" \
  --insecure \
  --plugin-type clientapp \
  --appio-api-address supernode-1:9094

echo ">>> Starting the client app for supernode 2 (clientapp)..."
docker run -d --rm \
  --network "$NETWORK_NAME" \
  --name superexec-clientapp-2 \
  "$CLIENT_IMAGE" \
  --insecure \
  --plugin-type clientapp \
  --appio-api-address supernode-2:9095
  
echo "All containers started."
echo
echo "Use 'docker ps' to check them, and 'docker logs -f <container-name>' to see logs."
