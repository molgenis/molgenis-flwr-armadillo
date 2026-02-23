# Molgenis Flower Armadillo

A wrapper for running Flower federated learning with in conjuncture with Molgenis Armadillo.

## Overview
The open-source edition of flower doesn't include individual-level authentication. This package extends flower by providing
CLI tools to 1) authenticate with Armadillo supernodes and 2) run Flower using these tokens.

## Installation

```bash
pip install -e .
```

## Quick Start

```bash
# 1. Authenticate to all nodes (opens browser for each)
molgenis-flwr-authenticate --config examples/quickstart-pytorch/flower-nodes.yaml

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
│    demo:                   token-demo = ""           --node-config \        │
│    localhost:              token-localhost = ""      'node-name="demo"'     │
└─────────────────────────────────────────────────────────────────────────────┘
```

**All three must use the same node names!**

In production, each site configures their `node-name` in the Armadillo UI. The site admin sets this when setting up their Armadillo instance for federated learning.

## File Configuration

### 1. `flower-nodes.yaml` - Define your Armadillo servers

Save this in your Flower app directory (e.g., `examples/quickstart-pytorch/flower-nodes.yaml`):

```yaml
nodes:
  demo:
    url: "https://armadillo-demo.molgenis.net"
  localhost:
    url: "https://armadillo.dev.molgenis.org"
```

The node names (`demo`, `localhost`) are used to:
- Name the tokens (`token-demo`, `token-localhost`)
- Match with SuperNode `node-name` configuration

### 2. `pyproject.toml` - App configuration (in your Flower app)

```toml
[tool.flwr.app.config]
num-server-rounds = 3
fraction-evaluate = 0.5
local-epochs = 1
learning-rate = 0.1
batch-size = 32
token-demo = ""
token-localhost = ""

[tool.flwr.federations]
default = "local-deployment"

[tool.flwr.federations.local-deployment]
address = "127.0.0.1:9093"
insecure = true
```

**Important:** Token keys must match node names from `flower-nodes.yaml`.

### 3. SuperNode `node-name` - Configured by each site

In production, each site's Armadillo admin configures their `node-name` in the Armadillo UI. This is set once when the site joins the federation.

The researcher must use matching names in `flower-nodes.yaml` and `pyproject.toml`.

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

For local testing, use Docker Compose to simulate the SuperNodes. The `node-name` is set via command line args (in production this is configured in the Armadillo UI).

See `examples/docker/` for the full setup. The key configuration is:

```yaml
supernode-demo:
  image: flwr/supernode:1.23.0
  command:
    - --insecure
    - --superlink=superlink:9092
    - --node-config
    - 'partition-id=0 num-partitions=2 node-name="demo"'
    - --clientappio-api-address=0.0.0.0:9094
    - --isolation=process
```

**Important:** `node-name` must match the names in `flower-nodes.yaml` and `pyproject.toml`.

### Quick start

```bash
# 1. Build the client app image
cd examples/quickstart-pytorch
docker build -f superexec.Dockerfile -t superexec-test:1.0.0 .

# 2. Start the infrastructure
cd ../docker
docker compose up -d

# 3. Authenticate
cd ../..
molgenis-flwr-authenticate --config examples/quickstart-pytorch/flower-nodes.yaml

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
Check that node names match:
- `flower-nodes.yaml` node names
- `pyproject.toml` token keys
- SuperNode `node-name` (configured in Armadillo UI, or docker-compose for local testing)
