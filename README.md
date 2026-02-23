# Molgenis Flower Armadillo

A wrapper for running Flower federated learning with in conjuncture with Molgenis Armadillo.

## Overview

This package provides CLI tools to authenticate with multiple Armadillo servers and run Flower federated learning jobs with automatic token injection.

## Installation

```bash
pip install -e .
```

## Quick Start

```bash
# 1. Authenticate to all nodes (opens browser for each)
molgenis-flwr-authenticate --config flower-nodes.yaml

# 2. Run the Flower app with tokens automatically injected
molgenis-flwr-run --app-dir examples/quickstart-pytorch
```

## Configuration Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           NAME ALIGNMENT REQUIRED                           │
│                                                                             │
│  flower-nodes.yaml    →    pyproject.toml    →    SuperNode startup        │
│  (researcher config)       (app config)           (specified by each site) │
│                                                                             │
│  nodes:                    [tool.flwr.app.config]  flower-supernode \       │
│    barcelona:              token-barcelona = ""      --node-config \        │
│    groningen:              token-groningen = ""      'node-name="barcelona"'│
└─────────────────────────────────────────────────────────────────────────────┘
```

**All three must use the same node names!**

In production, each site (Barcelona, Groningen, etc.) configures their `node-name` in the Armadillo UI. The site admin sets this when setting up their Armadillo instance for federated learning.

## File Configuration

### 1. `flower-nodes.yaml` - Define your Armadillo servers

```yaml
nodes:
  barcelona:
    url: "https://armadillo.isglobal.org"
  groningen:
    url: "https://armadillo.umcg.nl"
```

The node names (`barcelona`, `groningen`) are used to:
- Name the tokens (`token-barcelona`, `token-groningen`)
- Match with SuperNode `node-name` configuration

### 2. `pyproject.toml` - App configuration (in your Flower app)

```toml
[tool.flwr.app.config]
num-server-rounds = 3
fraction-evaluate = 0.5
local-epochs = 1
learning-rate = 0.1
batch-size = 32
token-barcelona = ""
token-groningen = ""

[tool.flwr.federations]
default = "local-deployment"

[tool.flwr.federations.local-deployment]
address = "127.0.0.1:9093"
insecure = true
```

**Important:** Token keys must match node names from `flower-nodes.yaml`.

### 3. `docker-compose.yml` - SuperNode configuration

```yaml
supernode-barcelona:
  image: flwr/supernode:1.23.0
  command:
    - --insecure
    - --superlink=superlink:9092
    - --node-config
    - 'partition-id=0 num-partitions=2 node-name="barcelona"'
    - --clientappio-api-address=0.0.0.0:9094
    - --isolation=process

supernode-groningen:
  image: flwr/supernode:1.23.0
  command:
    - --insecure
    - --superlink=superlink:9092
    - --node-config
    - 'partition-id=1 num-partitions=2 node-name="groningen"'
    - --clientappio-api-address=0.0.0.0:9095
    - --isolation=process
```

**Important:** `node-name` must match the node names from `flower-nodes.yaml`.

## Token Flow

```
User                    SuperLink              SuperNode
  │                         │                      │
  │ molgenis-flwr-authenticate                     │
  │ (opens browser for each node)                  │
  │                         │                      │
  │ molgenis-flwr-run       │                      │
  │ ───────────────────────>│                      │
  │ (tokens in --run-config)│                      │
  │                         │                      │
  │                    ServerApp                   │
  │                    reads tokens                │
  │                    from run_config             │
  │                         │                      │
  │                         │ ConfigRecord         │
  │                         │ (all tokens)         │
  │                         │─────────────────────>│
  │                         │                      │
  │                         │               ClientApp
  │                         │               extracts token
  │                         │               by node-name
  │                         │                      │
```

## Code Changes Required

### server_app.py

The server must forward tokens to clients via ConfigRecord:

```python
@app.main()
def main(grid: Grid, context: Context) -> None:
    # Read config
    lr: float = context.run_config["learning-rate"]

    # Collect all tokens to pass to clients
    tokens = {k: v for k, v in context.run_config.items() if k.startswith("token-")}

    # Build train config with tokens
    train_config = {"lr": lr, **tokens}

    result = strategy.start(
        grid=grid,
        initial_arrays=arrays,
        train_config=ConfigRecord(train_config),
        num_rounds=num_rounds,
    )
```

### client_app.py

Each client extracts its token based on its node-name:

```python
@app.train()
def train(msg: Message, context: Context):
    # Read token based on node name (passed via ConfigRecord from server)
    node_name = context.node_config["node-name"]
    token = msg.content["config"].get(f"token-{node_name}", "")
    print(f"[{node_name}] Using token: {token[:50]}...")

    # Use token to authenticate with Armadillo data source
    # ...
```

## Running Locally with Docker

```bash
# 1. Build the client app image
cd examples/quickstart-pytorch
docker build -f superexec.Dockerfile -t superexec-test:1.0.0 .

# 2. Start the infrastructure
cd ../docker
docker compose up -d

# 3. Authenticate
cd ../..
molgenis-flwr-authenticate --config flower-nodes.yaml

# 4. Run
molgenis-flwr-run --app-dir examples/quickstart-pytorch

# 5. View logs
docker compose logs -f

# 6. Stop
docker compose down
```

## Troubleshooting

### "Key 'token-xxx' is not present in the main dictionary"
The token key in `--run-config` doesn't exist in `pyproject.toml`. Add it:
```toml
[tool.flwr.app.config]
token-xxx = ""
```

### "KeyError: 'node-name'"
You're running in simulation mode which doesn't support `node-name`. Use deployment mode instead (docker-compose).

### Tokens showing as empty
Check that node names match across all three files:
- `flower-nodes.yaml` node names
- `pyproject.toml` token keys
- `docker-compose.yml` `node-name` values
