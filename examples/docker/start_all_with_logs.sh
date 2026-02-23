#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLIENT_IMAGE="${1:-superexec-test:0.0.1}"

echo ">>> Starting SuperLink..."
"$SCRIPT_DIR/start_super_link.sh" "$CLIENT_IMAGE"

echo ">>> Waiting for SuperLink to be ready..."
sleep 2

echo ">>> Starting SuperNodes..."
"$SCRIPT_DIR/start_two_local_super_nodes.sh" "$CLIENT_IMAGE"

echo ">>> Waiting for containers to start..."
sleep 2

echo ">>> Opening log windows..."

# Create temp scripts for each log window
for container in superlink supernode-1 supernode-2 superexec-clientapp-1 superexec-clientapp-2; do
  TMPSCRIPT=$(mktemp /tmp/log_${container}.XXXXXX.command)
  echo "#!/bin/bash" > "$TMPSCRIPT"
  echo "echo '=== Logs for $container ==='" >> "$TMPSCRIPT"
  echo "docker logs -f $container" >> "$TMPSCRIPT"
  chmod +x "$TMPSCRIPT"
  open "$TMPSCRIPT"
done

echo ""
echo "=== All containers started ==="
echo ""
echo "Containers running:"
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
echo ""
echo "To run the app:"
echo "  cd ../quickstart-pytorch && flwr run . local-deployment"
echo ""
echo "To stop everything:"
echo "  $SCRIPT_DIR/stop_all.sh"