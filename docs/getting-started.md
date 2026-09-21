# Getting Started

## Prerequisites

- Python 3.11+
- Access to one or more MOLGENIS Armadillo servers
- A Flower SuperLink and SuperNode deployment

## Configuration

### 1. Create `flower-nodes.yaml`

List the Armadillo servers you want to authenticate to:

```yaml
urls:
  - "https://armadillo-demo.molgenis.net"
  - "https://armadillo.dev.molgenis.org"
```

### 2. Add the token placeholder to `pyproject.toml`

All node tokens travel in one run-config key. Declare it empty:

```toml
[tool.flwr.app.config]
armadillo-tokens = ""
```

### 3. Authenticate

```bash
armadillo-flwr-authenticate --config flower-nodes.yaml
```

This opens a browser for OIDC authentication to each server and saves tokens locally.

### 4. Run your Flower app

```bash
armadillo-flwr-run .
```

Tokens are automatically injected into `flwr run --run-config`.

## Writing a Flower App

### Server app

The server collects tokens from the run config and forwards them to clients:

```python
from molgenis_flwr_armadillo import extract_tokens

@app.main()
def main(grid: Grid, context: Context) -> None:
    tokens = extract_tokens(context)
    train_config = {"lr": 0.01, **tokens}
    # pass train_config to strategy...
```

### Client app

Each client reads its URL and token from the environment / config:

```python
from molgenis_flwr_armadillo import get_node_token, get_node_url, load_data

@app.train()
def train(msg: Message, context: Context):
    url = get_node_url()
    token = get_node_token(msg)
    raw = load_data(url, token, "my-project", "train.parquet")
    df = pd.read_parquet(io.BytesIO(raw))
    # train model...
```
