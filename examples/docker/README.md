# Local Testing with Docker

This directory contains Docker configuration for testing the Flower + Armadillo integration locally.

## Prerequisites

- Docker and Docker Compose
- The `molgenis-flwr-armadillo` package installed (`pip install -e .` from repo root)

## Name Alignment

For testing, the node names must match across three files:

| flower-nodes.yaml | pyproject.toml | docker-compose.yml |
|-------------------|----------------|-------------------|
| `demo:` | `token-demo = ""` | `node-name="demo"` |
| `localhost:` | `token-localhost = ""` | `node-name="localhost"` |

## Quick Start

### 1. Build the client app image

```bash
cd ../quickstart-pytorch
docker build -f superexec.Dockerfile -t superexec-test:1.0.0 .
```

### 2. Start the infrastructure

```bash
cd ../docker
docker compose up -d
```

This starts:
- `superlink` - Central coordinator
- `supernode-demo` - SuperNode with `node-name="demo"`
- `supernode-localhost` - SuperNode with `node-name="localhost"`
- `clientapp-demo` - Client app for demo node
- `clientapp-localhost` - Client app for localhost node
- `serverapp` - Server app

### 3. Authenticate

```bash
cd ../..
armadillo-flwr-authenticate --config examples/quickstart-pytorch/flower-nodes.yaml
```

This opens a browser for each node to authenticate via OAuth.

### 4. Run the Flower app

```bash
armadillo-flwr-run --app-dir examples/quickstart-pytorch
```

### 5. View logs

```bash
# All logs
docker compose logs -f

# Specific service
docker compose logs -f clientapp-demo
docker compose logs -f serverapp
```

### 6. Stop everything

```bash
docker compose down
```

## Modifying Node Names

To change node names (e.g., from `demo`/`localhost` to `barcelona`/`groningen`), update all three files:

### examples/quickstart-pytorch/flower-nodes.yaml
```yaml
nodes:
  barcelona:
    url: "https://armadillo.isglobal.org"
  groningen:
    url: "https://armadillo.umcg.nl"
```

### examples/quickstart-pytorch/pyproject.toml
```toml
[tool.flwr.app.config]
token-barcelona = ""
token-groningen = ""
```

### examples/docker/docker-compose.yml
```yaml
supernode-barcelona:
  command:
    - --node-config
    - 'partition-id=0 num-partitions=2 node-name="barcelona"'

supernode-groningen:
  command:
    - --node-config
    - 'partition-id=1 num-partitions=2 node-name="groningen"'
```

Then rebuild and restart:
```bash
cd ../quickstart-pytorch
docker build -f superexec.Dockerfile -t superexec-test:1.0.0 .
cd ../docker
docker compose down
docker compose up -d
```

## Troubleshooting

### "No space left on device"
```bash
docker system prune -a
```

### Tokens showing as empty
Check that node names match in all three configuration files (see above).

### "KeyError: 'node-name'"
Make sure you're using `local-deployment` federation, not `local-simulation`. Check `pyproject.toml`:
```toml
[tool.flwr.federations]
default = "local-deployment"
```

### Container keeps restarting
Check logs for the specific container:
```bash
docker compose logs serverapp
```
