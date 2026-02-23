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

## Stage 5: Per-Container Permissions

**Goal:** Extend Armadillo's permission model so users have access to specific containers (DataSHIELD profiles or Flower client-apps), not just projects.

### Current Model

```
User → Project → [all containers]
```

All authenticated users with project access can use any container.

### Target Model

```
User → Project → Container(s) they're permitted to use
                    ├── DataSHIELD: default, donkey, panda-lambda
                    └── Flower: lung-cancer-fl, diabetes-study
```

### Changes

**1. Armadillo: Extend permission data model**

Update `ProjectPermission` to include container:

```java
// Before
public record ProjectPermission(String email, String project) {}

// After
public record ProjectPermission(String email, String project, String container) {}
```

Update `access.json` structure:
```json
{
  "permissions": [
    {"email": "user@example.com", "project": "cohort-study", "container": "default"},
    {"email": "user@example.com", "project": "cohort-study", "container": "lung-cancer-fl"}
  ]
}
```

**2. Armadillo: Update role generation**

In `AccessService.getAuthoritiesForEmail()`:

```java
// Before
"ROLE_" + project.toUpperCase() + "_RESEARCHER"

// After
"ROLE_" + project.toUpperCase() + "_" + container.toUpperCase() + "_RESEARCHER"
```

**3. Armadillo: Add authorization checks**

DataSHIELD container selection:
```java
// In ProfileService or similar
@PreAuthorize("hasAnyRole('ROLE_SU', 'ROLE_' + #project.toUpperCase() + '_' + #container.toUpperCase() + '_RESEARCHER')")
public void selectProfile(String project, String container) { ... }
```

Flower data fetch (client-app must identify itself):
```java
@PreAuthorize("hasAnyRole('ROLE_SU', 'ROLE_' + #project.toUpperCase() + '_' + #appId.toUpperCase() + '_RESEARCHER')")
public InputStream loadObjectForApp(String project, String object, String appId) { ... }
```

**4. Armadillo: Permission management API**

New/updated endpoints in `AccessController`:
```
POST   /access/projects/{project}/containers/{container}/users
DELETE /access/projects/{project}/containers/{container}/users/{email}
GET    /access/projects/{project}/containers
GET    /access/users/{email}/containers
```

**5. Armadillo: UI extension**

Extend user management page to show/edit container permissions per project. Minimal change - add a multi-select or checkbox list for containers.

**6. Migration strategy**

For existing permissions without container specified:
- Option A: Grant access to ALL containers (backwards compatible)
- Option B: Grant access to a "default" container only (more restrictive)

Recommend Option A for smooth migration.

**7. Flower client-app: Pass app ID when fetching data**

Update `fetch_from_armadillo()` to include app identifier:
```python
def fetch_from_armadillo(url: str, project: str, object_name: str, token: str, app_id: str) -> bytes:
    endpoint = f"{url}/storage/projects/{project}/objects/{object_name}"
    headers = {
        "Authorization": f"Bearer {token}",
        "X-App-Id": app_id  # or as query param
    }
    ...
```

### Verification

1. User with container permission can access that container
2. User without container permission gets 403
3. Existing permissions continue to work (migration)
4. Both DataSHIELD and Flower apps respect container permissions

### Done when

- Permission model extended with container field
- Authorization checks enforce container access
- API endpoints for managing container permissions
- UI allows assigning users to containers
- Flower client-apps pass app ID and permissions are enforced

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

## Helper Functions for Researchers

**Goal:** Reduce boilerplate in researcher code by providing helper functions in `molgenis_flwr_armadillo` for token handling.

### Current Pain Point

Researchers must copy token-handling code into their apps:

**Server side:**
```python
# Collect all tokens from run_config to pass to clients
tokens = {k: v for k, v in context.run_config.items() if k.startswith("token-")}
train_config = ConfigRecord({"lr": lr, **tokens})
```

**Client side:**
```python
node_name = context.node_config["node-name"]
token = msg.content["config"].get(f"token-{node_name}", "")
```

### Solution: Helper Functions

Add to `src/molgenis_flwr_armadillo/helpers.py`:

```python
"""Helper functions for token handling in Flower apps."""

from flwr.app import Context, Message


def extract_tokens(context: Context) -> dict:
    """Extract all tokens from run_config for passing to clients.

    Use in server_app.py to collect tokens for the train_config.

    Args:
        context: The Flower Context object

    Returns:
        Dict of token keys to token values, e.g. {"token-demo": "eyJ..."}

    Example:
        tokens = extract_tokens(context)
        train_config = ConfigRecord({"lr": lr, **tokens})
    """
    return {k: v for k, v in context.run_config.items() if k.startswith("token-")}


def get_node_token(msg: Message, context: Context) -> str:
    """Extract this node's token from the message config.

    Use in client_app.py to get the token for this specific node.

    Args:
        msg: The Flower Message received from the server
        context: The Flower Context object

    Returns:
        The token string for this node, or empty string if not found

    Example:
        token = get_node_token(msg, context)
        data = fetch_from_armadillo(token)
    """
    node_name = context.node_config.get("node-name", "")
    return msg.content.get("config", {}).get(f"token-{node_name}", "")
```

### Updated Researcher Code

**Server side:**
```python
from molgenis_flwr_armadillo import extract_tokens

@app.main()
def main(grid: Grid, context: Context) -> None:
    lr = context.run_config["learning-rate"]
    tokens = extract_tokens(context)
    train_config = ConfigRecord({"lr": lr, **tokens})
    # ...
```

**Client side:**
```python
from molgenis_flwr_armadillo import get_node_token

@app.train()
def train(msg: Message, context: Context):
    token = get_node_token(msg, context)
    # Use token to fetch data from Armadillo
    # ...
```

### Changes Required

1. **New file:** `src/molgenis_flwr_armadillo/helpers.py` — the helper functions
2. **Update:** `src/molgenis_flwr_armadillo/__init__.py` — export the helpers
3. **Update:** `README.md` — document the helper functions
4. **Update:** Example apps — use the helpers instead of inline code

### Done when
- Helper functions are implemented and exported
- Examples use the helper functions
- README documents the helpers

---

## Error Handling for Data Fetches

**Goal:** Provide clear, actionable error messages when Armadillo data requests fail, rather than generic HTTP errors.

### Approach

We chose **not** to validate tokens upfront because:
1. Token validity alone isn't enough — project/data access must also be checked
2. The coordinator doesn't know what specific data the app will request
3. Upfront validation adds complexity and extra network calls

Instead, we invest in **clear error messages at the point of failure**.

### Implementation

Wrap all Armadillo HTTP requests with descriptive error handling:

```python
class ArmadilloError(Exception):
    """Base exception for Armadillo access errors."""
    pass

class AuthenticationError(ArmadilloError):
    """Token is invalid or expired."""
    pass

class AccessDeniedError(ArmadilloError):
    """User lacks permission to access this resource."""
    pass

class ResourceNotFoundError(ArmadilloError):
    """Requested project or object does not exist."""
    pass


def fetch_from_armadillo(url: str, project: str, object_name: str, token: str) -> bytes:
    """Fetch data from Armadillo with clear error handling."""
    endpoint = f"{url}/storage/projects/{project}/objects/{object_name}"
    headers = {"Authorization": f"Bearer {token}"}

    resp = requests.get(endpoint, headers=headers)

    if resp.status_code == 401:
        raise AuthenticationError(
            f"Authentication failed for '{url}'.\n"
            f"Token may be expired — re-run: molgenis-flwr-authenticate"
        )
    if resp.status_code == 403:
        raise AccessDeniedError(
            f"Access denied to project '{project}' on '{url}'.\n"
            f"Check your permissions in Armadillo."
        )
    if resp.status_code == 404:
        raise ResourceNotFoundError(
            f"Object '{object_name}' not found in project '{project}'.\n"
            f"Available data can be listed with: molgenis-flwr-tables"
        )

    resp.raise_for_status()
    return resp.content
```

### Error messages should:
- Identify which node/server had the problem
- Explain what went wrong in plain language
- Suggest a remediation action
- Propagate cleanly back to the user (not buried in stack traces)

### Done when
- All Armadillo requests use the error-handling wrapper
- Error messages are clear and actionable
- Errors propagate to the user with node context

---

## List Available Data (`molgenis-flwr-tables`)

**Goal:** Provide a way for researchers to see what data they have access to on each Armadillo node, similar to `datashield.tables()`. Run this after authentication but before `molgenis-flwr-run`.

### Usage

```bash
# After authenticating
molgenis-flwr-authenticate --config flower-nodes.yaml

# List available tables/data on all nodes
molgenis-flwr-tables --config flower-nodes.yaml
```

Output:
```
Node: demo (https://armadillo-demo.molgenis.net)
  Projects:
    - cifar10
      - partitions/partition_0_train.pt
      - partitions/partition_0_test.pt
    - cohort_data
      - tables/demographics
      - tables/outcomes

Node: localhost (https://armadillo.dev.molgenis.org)
  Projects:
    - cifar10
      - partitions/partition_1_train.pt
      - partitions/partition_1_test.pt
```

### Implementation

Add CLI entry point in `pyproject.toml`:
```toml
[project.scripts]
molgenis-flwr-tables = "molgenis_flwr_armadillo.tables:main"
```

New file `src/molgenis_flwr_armadillo/tables.py`:
```python
"""List available data on Armadillo nodes."""

import requests
from .authenticate import load_tokens

def list_projects(url: str, token: str) -> list[str]:
    """List projects the user has access to."""
    resp = requests.get(
        f"{url}/storage/projects",
        headers={"Authorization": f"Bearer {token}"}
    )
    resp.raise_for_status()
    return resp.json()

def list_objects(url: str, project: str, token: str) -> list[str]:
    """List objects in a project."""
    resp = requests.get(
        f"{url}/storage/projects/{project}/objects",
        headers={"Authorization": f"Bearer {token}"}
    )
    resp.raise_for_status()
    return resp.json()

def main():
    # Load config and tokens, list data for each node
    ...
```

### Programmatic access

Also expose as a helper function for use in code:
```python
from molgenis_flwr_armadillo import list_available_data

# Returns dict of node -> projects -> objects
data = list_available_data(config_path="flower-nodes.yaml")
```

### Done when
- CLI command `molgenis-flwr-tables` works
- Helper function `list_available_data()` is exported
- Output is clear and shows the hierarchy

---

## Known Risks

1. **Shell escaping**: Long JWT tokens on the command line may cause issues. May need a config file approach.
2. **Token TTL**: Default 300s. Fine for simulation. For production, increase or implement refresh.
3. **rawfiles object name matching**: `StorageController.java:440-441` strips extension and lowercases. Token generation must match.
4. **Data security**: Data is held in memory only — never written to disk. Containers should be ephemeral.

---

## Progress Checklist

### Infrastructure
- [x] Package structure (`molgenis_flwr_armadillo`)
- [x] CLI tool: `molgenis-flwr-authenticate`
- [x] CLI tool: `molgenis-flwr-run`
- [x] Token storage/retrieval (`save_tokens`, `load_tokens`)
- [ ] Helper functions (`extract_tokens`, `get_node_token`)
- [ ] CLI tool: `molgenis-flwr-tables` (list available data)
- [ ] Helper function: `list_available_data()`
- [ ] Error handling wrapper for Armadillo requests

### Stage 1: Token String Routing POC
- [x] Token placeholder keys in `pyproject.toml`
- [x] Token extraction in client_app.py
- [x] Token forwarding via ConfigRecord in server_app.py
- [x] End-to-end token flow verified

### Stage 2: Armadillo Data Access
- [ ] Setup script for uploading data to Armadillo
- [ ] `download_from_armadillo()` function
- [ ] Client data loading from Armadillo
- [ ] Server global evaluation from Armadillo
- [ ] End-to-end data flow verified

### Stage 3: Token-Authenticated Access
- [ ] Armadillo: token generation endpoint
- [ ] Armadillo: token-authenticated download endpoint
- [ ] Script to obtain resource tokens
- [ ] Per-partition token keys in config
- [ ] Token-based download in task.py
- [ ] End-to-end authenticated flow verified

### Stage 4: Differential Privacy
- [ ] DP strategy wrapper in server_app.py
- [ ] Clipping mod in client_app.py
- [ ] DP config parameters
- [ ] Privacy-utility tradeoff documented

### Stage 5: Per-Container Permissions
- [ ] Armadillo: Extend `ProjectPermission` with container field
- [ ] Armadillo: Update role generation for container-scoped roles
- [ ] Armadillo: Add `@PreAuthorize` checks for container access
- [ ] Armadillo: Permission management API endpoints
- [ ] Armadillo: UI extension for container permissions
- [ ] Armadillo: Migration for existing permissions
- [ ] Flower: Pass app ID when fetching data

### Documentation
- [x] README with usage instructions
- [x] Configuration flow diagram
- [x] Token flow diagram
- [ ] Helper functions documented in README