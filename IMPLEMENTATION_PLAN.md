# Flower + Armadillo Integration: Staged Implementation Plan

## Context

We need to enable Flower federated learning clients (running in Docker) to access training data stored in MOLGENIS Armadillo, with proper authentication. The work is split into four sequential stages — each is completed and verified before moving to the next.

**Repositories:**
- Flower quickstart (prototyping): `/Users/timcadman/git-repos/flower/quickstart-pytorch/`
- Armadillo: `/Users/timcadman/git-repos/molgenis/molgenis-service-armadillo/` — work on branch `epic/flower`
- Python wrapper packages: `https://github.com/molgenis/molgenis-flwr-armadillo` — branch `epic/flower`, PRs go into that branch

**Branching:**
- Any Armadillo Java changes (e.g., new endpoints in Stage 3) are developed on `epic/flower` in `molgenis-service-armadillo`
- All Python work (Flower app, setup scripts, token retrieval, client utilities) lives in `molgenis-flwr-armadillo` on branch `epic/flower`
- The Flower app itself (based on the quickstart-pytorch example) will be copied into `molgenis-flwr-armadillo` so everything is in one place

---

## Stage 1: Realistic Data Split + Token String Routing POC

**Goal:** (a) Modify the example so each node holds a distinct, predetermined portion of CIFAR-10 (first half / second half) rather than a random IID split, and (b) pass fake token strings via `flwr run --run-config` and verify each client receives its correct token.

### Changes

**1. `pyproject.toml`** — add token placeholder config keys:
```toml
[tool.flwr.app.config]
# ... existing keys ...
token-0 = ""
token-1 = ""
```

**2. `pytorchexample/task.py`** — replace the IID partitioning with a sequential split:
- Currently uses `FederatedDataset` with `IidPartitioner` (random sampling)
- Change to a deterministic sequential split: partition 0 gets the first half of the training data, partition 1 gets the second half
- This better represents a real scenario where each institution holds its own distinct data

**3. `pytorchexample/client_app.py`** — extract and log the token in both `train()` and `evaluate()`:
```python
partition_id = context.node_config["partition-id"]
token_key = f"token-{partition_id}"
my_token = context.run_config.get(token_key, "")
print(f"[Client {partition_id}] Received token: '{my_token}'")
```

No changes to `server_app.py`.

### Verification
```bash
flwr run . --run-config "token-0=fake-token-node-0 token-1=fake-token-node-1"
```
- Each client logs the correct token for its partition ID
- Training still works with the sequential split (accuracy may differ slightly from IID)

### Done when
- Data is split deterministically (not randomly) and each node has a distinct portion
- Each simulated client prints the token that corresponds to its partition ID

---

## Stage 2: Armadillo Data Access via Objects Endpoint

**Goal:** Store CIFAR-10 partitions in Armadillo and have Flower clients download their partition via the objects endpoint (`GET /storage/projects/{project}/objects/{object}`) with admin basic auth.

### Changes

**1. `pyproject.toml`** — add `requests` dependency and Armadillo config:
```toml
dependencies = [
    # ... existing ...
    "requests>=2.31.0",
]

[tool.flwr.app.config]
# ... existing + stage 1 keys ...
armadillo-url = ""
armadillo-project = "cifar10"
armadillo-user = "admin"
armadillo-pass = "admin"
```

**2. New file: `scripts/setup_armadillo_data.py`** — setup script that:
- Downloads CIFAR-10 via `FederatedDataset` (same as current `task.py`)
- Partitions into N partitions, splits 80/20 train/test
- Saves each split as `.pt` files (`{"images": tensor, "labels": tensor}`)
- Creates the `cifar10` project in Armadillo
- Uploads each partition via `POST /storage/projects/cifar10/objects`
- Uploads full test set as `test/global_test.pt` for server-side evaluation

Armadillo object structure:
```
Project: cifar10
  partitions/partition_0_train.pt
  partitions/partition_0_test.pt
  partitions/partition_1_train.pt
  partitions/partition_1_test.pt
  test/global_test.pt
```

**3. `pytorchexample/task.py`** — add Armadillo download functions:
- `download_from_armadillo(url, project, object_name, auth=None, token=None)` — downloads a `.pt` file via HTTP (objects endpoint with basic auth for now; token path added in stage 3)
- `load_data_from_armadillo(partition_id, batch_size, ...)` — downloads train + test partitions, returns DataLoaders from TensorDatasets
- `load_centralized_from_armadillo(...)` — downloads the global test set
- Update `train()` and `test()` to handle both dict batches (`batch["img"]`) and tuple batches (`batch[0]`) since TensorDataset returns tuples
- **Data cleanup:** after loading data into memory, delete the downloaded bytes/temp data so nothing persists on disk

**4. `pytorchexample/client_app.py`** — branch data loading:
- If `armadillo-url` is set in run_config, use `load_data_from_armadillo()`
- Otherwise fall back to existing `load_data()`

**5. `pytorchexample/server_app.py`** — update global evaluation:
- Move `global_evaluate` inside `main()` as a closure to access Armadillo config
- If `armadillo-url` is set, use `load_centralized_from_armadillo()`

### Verification
```bash
# 1. Start Armadillo
docker-compose up -d armadillo

# 2. Upload CIFAR-10 partitions
python scripts/setup_armadillo_data.py --num-partitions 2

# 3. Run Flower
flwr run . --run-config "armadillo-url=http://localhost:8080 armadillo-project=cifar10"
```
- No HTTP errors
- Training proceeds with decreasing loss, global evaluation reports accuracy

### Done when
Flower clients successfully download CIFAR-10 from Armadillo and train with results comparable to the original demo.

---

## Stage 3: Token-Authenticated Access

**Goal:** Replace basic auth with internal token-based auth. The key idea is Armadillo's internal token pattern (short-lived, scoped JWTs signed with in-memory RSA keys). We may use the existing rawfiles endpoint or write a new dedicated endpoint — whichever works cleanest.

### The internal token approach

Armadillo's `ResourceTokenService` generates JWTs with:
- Issuer: `"http://armadillo-internal"`
- Claims: `resource_project`, `resource_object`, `email`
- RSA-signed, configurable TTL (default 300s)

This is the pattern we want to reuse. The existing rawfiles endpoint (`/rawfiles/{object}`) validates these tokens. If it works well for our needs, we use it directly. If not (e.g., per-object scoping is too restrictive), we write a new endpoint following the same token validation pattern but with broader scope (e.g., project-level access).

### Changes

**1. Armadillo: new token generation endpoint** — expose `ResourceTokenService` via API:
- Add `ResourceTokenService` as a dependency to `StorageController` (currently only `CommandsImpl` uses it)
- New endpoint, e.g.: `GET /storage/projects/{project}/resource-token/{object}`
- Requires authentication (ROLE_SU or project researcher)
- Returns `{"token": "<jwt-value>"}`
- Calls existing `resourceTokenService.generateResourceToken()`

**2. Armadillo: potentially a new data download endpoint** — if rawfiles doesn't fit:
- Alternative endpoint with project-level token scope instead of per-object
- Same internal token validation pattern
- Decision deferred until we test rawfiles in practice

**3. `scripts/get_tokens.py`** — new script to obtain tokens before `flwr run`:
- Authenticates to Armadillo
- Requests resource tokens for each partition's train and test data
- Outputs `flwr run` command with tokens

**4. `pyproject.toml`** — per-partition train/test token keys:
```toml
token-0-train = ""
token-0-test = ""
token-1-train = ""
token-1-test = ""
```

**5. `pytorchexample/task.py`** — update `download_from_armadillo()`:
- When `token` is provided: call rawfiles (or new endpoint) with `Authorization: Bearer <token>`
- When `auth` is provided: fall back to objects endpoint (stage 2 mode)

**6. `pytorchexample/client_app.py`** — read per-object tokens from run_config

### Data security within Docker

Critical requirement: training data must not persist in the Docker container after the job completes.

- **In-memory only:** `download_from_armadillo()` loads data into `io.BytesIO` → `torch.load()` → Python tensors. No files written to disk.
- **Explicit cleanup:** after training completes, explicitly `del` the data tensors and call `gc.collect()` to release memory
- **Container lifecycle:** in production deployment, the Docker container running the Flower client should be ephemeral — created for the job and destroyed after. Any tmpfs or writable layer is discarded.
- **No caching:** unlike the current `fds` global cache pattern, Armadillo-sourced data is NOT cached between rounds. It's loaded fresh each time (or held only in memory for the duration of training).

### Verification
```bash
# 1. Deploy Armadillo with token endpoint
# 2. Get tokens
python scripts/get_tokens.py --num-partitions 2
# 3. Run Flower with tokens only (no armadillo-user/pass)
flwr run . --run-config "armadillo-url=http://localhost:8080 armadillo-project=cifar10 token-0-train=eyJ... token-0-test=eyJ..."
```
- Armadillo audit logs show `DOWNLOAD_RESOURCE` events
- No basic auth credentials in the run config
- Data not persisted to disk in client

### Done when
Full end-to-end flow: authenticate → get scoped tokens → pass through Flower → download data via token → train → cleanup.

---

## Stage 4: Differential Privacy on Model Parameters

**Goal:** Add differential privacy to the model parameters exchanged between SuperNodes and SuperLink each round, so that updates from one node cannot leak information about that node's training data.

### Flower DP options

Flower provides three DP approaches. For our use case (protecting parameters in transit between nodes and server):

1. **Central DP, server-side clipping** — server clips and adds noise after receiving updates. Simpler but server sees raw updates briefly.
2. **Central DP, client-side clipping** — clients clip updates before sending, server adds noise after aggregation. Better privacy: server never sees unclipped updates.
3. **Local DP** — each client adds noise to its own updates before sending. Strongest privacy guarantee but typically reduces model accuracy more.

**Recommended: Client-side clipping** — good balance of privacy (clipping happens before data leaves the node) and utility (noise is calibrated centrally).

### Changes

**1. `pytorchexample/server_app.py`** — wrap FedAvg with DP strategy:
```python
from flwr.serverapp.strategy import DifferentialPrivacyClientSideFixedClipping

strategy = FedAvg(fraction_evaluate=fraction_evaluate)
dp_strategy = DifferentialPrivacyClientSideFixedClipping(
    strategy,
    noise_multiplier=noise_multiplier,
    clipping_norm=clipping_norm,
    num_sampled_clients=num_sampled_clients,
)
```

**2. `pytorchexample/client_app.py`** — add clipping mod:
```python
from flwr.clientapp.mod import fixedclipping_mod

app = ClientApp(mods=[fixedclipping_mod])
```

**3. `pyproject.toml`** — add DP config parameters:
```toml
[tool.flwr.app.config]
# ... existing keys ...
noise-multiplier = 1.0
clipping-norm = 1.0
num-sampled-clients = 2
```

### Key parameters to tune
- **`noise_multiplier`**: higher = more privacy, less accuracy. Start with 1.0.
- **`clipping_norm`**: max L2 norm of client updates. Start with 1.0 and adjust based on observed update magnitudes.
- **`num_sampled_clients`**: number of clients per round (affects noise calibration).

### Verification
- Run with DP enabled and verify training completes (accuracy will be lower than without DP — this is expected)
- Run with `noise_multiplier=0.0` to confirm results match the non-DP baseline
- Compare accuracy across different noise multiplier values to understand the privacy-utility tradeoff

### Done when
Model parameters are clipped on the client side and noise is added server-side before aggregation. Training completes with reasonable (if reduced) accuracy.

---

## Files Summary

All Python files are in `molgenis-flwr-armadillo` (`epic/flower` branch):

| File | Action | Stage |
|------|--------|-------|
| `pyproject.toml` | New (based on quickstart) | 1, 2, 3, 4 |
| `pytorchexample/client_app.py` | New (based on quickstart) | 1, 2, 3, 4 |
| `pytorchexample/task.py` | New (based on quickstart) | 1, 2, 3 |
| `pytorchexample/server_app.py` | New (based on quickstart) | 2, 4 |
| `scripts/setup_armadillo_data.py` | New | 2 |
| `scripts/get_tokens.py` | New | 3 |

Armadillo changes in `molgenis-service-armadillo` (`epic/flower` branch):

| File | Action | Stage |
|------|--------|-------|
| `StorageController.java` | Modify | 3 |

## Known Risks

1. **Shell escaping**: Long JWT tokens on the command line may cause issues. May need a config file approach.
2. **Token TTL**: Default 300s. Fine for simulation. For production, increase or implement refresh.
3. **rawfiles object name matching**: `StorageController.java:440-441` strips extension and lowercases. Token generation must match.
4. **Data security**: Data is held in memory only — never written to disk. Containers should be ephemeral.