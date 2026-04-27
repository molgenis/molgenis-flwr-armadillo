# Loading Data from Armadillo

## Overview

Data loading follows the same pattern as DataSHIELD's `assign.table()`: the client requests data, Armadillo pushes it into the container via Docker, and the helper reads it into memory and deletes the file immediately.

## The `load_data()` Function

```python
from molgenis_flwr_armadillo import get_node_token, get_node_url, load_data

url = get_node_url()
token = get_node_token(msg)
raw = load_data(url, token, "my-project", "train.parquet")
```

### What happens under the hood

1. `load_data()` calls `POST /flower/push-data` on Armadillo
2. Armadillo validates the OIDC token and checks project permissions
3. Armadillo reads the resource from storage
4. Armadillo copies the data into the container via Docker API
5. `load_data()` waits for the file to appear at `/tmp/armadillo_data/`
6. The file is read into memory as raw bytes
7. The file is deleted immediately
8. Raw bytes are returned

### File lifecycle

```
  Write     Read    Delete     Parse
    |         |        |         |
    └────┬────┴───┬────┘         └── Data in memory only
     File exists  |
                  └── File gone before researcher code runs
```

## Parsing the data

`load_data()` returns raw bytes. Parse with whatever library you need:

```python
import io
import pandas as pd

# Parquet
raw = load_data(url, token, "project", "data.parquet")
df = pd.read_parquet(io.BytesIO(raw))

# CSV
raw = load_data(url, token, "project", "data.csv")
df = pd.read_csv(io.BytesIO(raw))

# PyTorch tensor
import torch
raw = load_data(url, token, "project", "model.pt")
data = torch.load(io.BytesIO(raw))
```

## Checking access before training

Use `check_access()` to verify permissions before starting a long training run:

```python
from molgenis_flwr_armadillo import check_access

check_access(url, token, "my-project", ["train.parquet", "test.parquet"])
# Raises RuntimeError if user lacks access or resources don't exist
```

## Listing available data

```python
from molgenis_flwr_armadillo import list_projects, list_resources

projects = list_projects(url, token)
resources = list_resources(url, token, "my-project")
```

Or from the command line:

```bash
armadillo-flwr-resources
```
