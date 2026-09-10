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
armadillo-flwr-authenticate --config flower-nodes.yaml

# 2. Run the Flower app with tokens automatically injected
armadillo-flwr-run .
```

## Configuration Flow

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                           URL-BASED TOKEN ROUTING                            │
│                                                                              │
│  flower-nodes.yaml    →    pyproject.toml    →    Container env var         │
│  (researcher config)       (app config)           (set by Armadillo)       │
│                                                                              │
│  urls:                     [tool.flwr.app.config]  ARMADILLO_URL=           │
│    - "https://demo..."     armadillo-tokens = ""     "https://demo..."     │
│    - "https://dev..."                                                       │
└──────────────────────────────────────────────────────────────────────────────┘
```

Every token travels in one `armadillo-tokens` run-config value: a base64-encoded
JSON map of `{sanitized-url: token}`, where URLs are sanitized into safe keys
automatically (e.g. `https://armadillo-demo.molgenis.net` becomes
`armadillo-demo-molgenis-net`). Inside the container each client picks its own
token by matching the `ARMADILLO_URL` environment variable Armadillo injected.

## File Configuration

### 1. `flower-nodes.yaml` - Define your Armadillo servers

Save this in your Flower app directory:

```yaml
urls:
  - "https://armadillo-demo.molgenis.net"
  - "https://armadillo.dev.molgenis.org"
```

### 2. `pyproject.toml` - App configuration (in your Flower app)

```toml
[tool.flwr.app.config]
num-server-rounds = 3
fraction-evaluate = 0.5
local-epochs = 1
learning-rate = 0.1
batch-size = 32
armadillo-tokens = ""

[tool.flwr.federations]
default = "local-deployment"

[tool.flwr.federations.local-deployment]
address = "127.0.0.1:9093"
insecure = true
```

Declaring `armadillo-tokens` once is all the app needs: per-node keys are never
declared, which keeps the app publishable on Flower Hub.

### 3. `ARMADILLO_URL` - Set by Armadillo

Armadillo injects its URL into each container via the `ARMADILLO_URL`
environment variable. No manual configuration needed.

## Token Flow

```
User                    SuperLink              SuperNode
  │                         │                      │
  │ armadillo-flwr-authenticate                     │
  │ (opens browser for each URL)                   │
  │                         │                      │
  │ armadillo-flwr-run       │                      │
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
  │                         │               reads ARMADILLO_URL
  │                         │               from environment
  │                         │               matches token by
  │                         │               sanitized URL
  │                         │                      │
```

## Code Changes Required

### server_app.py

The server must forward tokens to clients via ConfigRecord:

```python
@app.main()
def main(grid: Grid, context: Context) -> None:
    lr: float = context.run_config["learning-rate"]
    tokens = extract_tokens(context)
    train_config = {"lr": lr, **tokens}

    result = strategy.start(
        grid=grid,
        initial_arrays=arrays,
        train_config=ConfigRecord(train_config),
        num_rounds=num_rounds,
    )
```

### client_app.py

Each client reads its URL from the environment and matches its token:

```python
@app.train()
def train(msg: Message, context: Context):
    token = get_node_token(msg)
    url = get_node_url()
    # Use token + url to authenticate with Armadillo
    # ...
```

## Running Locally with Docker

For local testing, use Docker Compose to simulate the containers.
Each container needs `ARMADILLO_URL` set as an environment variable.

See the [flower-examples](https://github.com/molgenis/flower-examples) repo for Docker Compose setup and example apps.

## Troubleshooting

### "Key 'armadillo-tokens' is not present in the main dictionary"
The app's `pyproject.toml` doesn't declare the token bundle key. Add it:
```toml
[tool.flwr.app.config]
armadillo-tokens = ""
```

### "ARMADILLO_URL environment variable not set"
The container was not started with `ARMADILLO_URL` set.
In production, Armadillo injects this automatically.

### Tokens showing as empty
Check that:
- `flower-nodes.yaml` URLs match the Armadillo server URLs
- `pyproject.toml` declares `armadillo-tokens`
- Container has `ARMADILLO_URL` set as an environment variable
