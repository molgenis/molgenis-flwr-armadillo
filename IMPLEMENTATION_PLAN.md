# Flower + Armadillo: Implementation Plan

## Overview

This document describes how Flower federated learning integrates with MOLGENIS Armadillo for secure data access. The design mirrors the existing DataSHIELD `assign.table` pattern: authenticated requests, server-side data push into the container, and immediate file deletion after loading into memory.

The key principle: **Armadillo pushes data into the container** (via `docker exec`). The container never pulls data from Armadillo. This is the same approach DataSHIELD uses with Rserve.

**Repositories:**
- **molgenis-service-armadillo** — Java changes (endpoint, docker exec push, security)
- **molgenis-flwr-armadillo** — Python package (CLI tools, helper functions, example apps)

---

## DataSHIELD vs Flower: Side-by-Side

| Step | DataSHIELD (assign.table) | Flower (push-data) |
|------|---------------------------|----------------------|
| **1. Researcher authenticates** | Gets OIDC token | Gets OIDC token |
| **2. Researcher triggers** | `datashield.assign.table()` | Submits Flower job with token in run_config |
| **3. Job arrives** | DSI sends HTTP to Armadillo | Flower delivers run_config to ClientApp |
| **4. HTTP request to Armadillo** | DSI calls `POST /load-table` | ClientApp calls `POST /flower/push-data` |
| **5. Auth** | Spring Security + `ROLE_<PROJECT>_RESEARCHER` | Spring Security + `ROLE_<PROJECT>_RESEARCHER` |
| **6. Read from storage** | `armadilloStorage.loadTable()` | `armadilloStorage.loadObject()` |
| **7. Data push** | Rserve `writeFile()` | `docker exec cat >` into container |
| **8. Load into memory** | R reads file internally | `load_data()` reads file into bytes |
| **9. File deleted** | `base::unlink()` | `filepath.unlink()` inside `load_data()` |
| **10. Code execution** | DataSHIELD functions (file gone) | `model.fit(df)` (file gone) |
| **11. Process ends** | R session ends, container stops | ClientApp exits, container stops |

### File Lifetime — Identical Pattern

```
DataSHIELD:
──────────────────────────────────────────────────────────────────►
     │         │         │
   Write     Load    Delete                      Researcher code
     │         │         │                              │
     └────┬────┴────┬────┘                              │
      File exists   └──── Data in memory only ──────────┘


Flower:
──────────────────────────────────────────────────────────────────►
     │       │       │       │
   Write   Read   Delete   Parse                  Researcher code
           bytes          bytes                         │
     │       │       │       │                          │
     └───┬───┴───┬───┘       └── Data in memory only ───┘
     File exists
```

In both cases, the file is deleted immediately after loading into memory, before the researcher's code runs.

---

## Request Flow

```
1. Researcher authenticates (OIDC) to each Armadillo via
   armadillo-flwr-authenticate. Tokens saved locally.

2. Researcher submits Flower job via armadillo-flwr-run.
   Tokens injected into Flower's --run-config as
   token-{sanitized-url}="eyJ..." key-value pairs.

3. Flower routes the job. ServerApp extracts tokens from
   run_config and forwards them to ClientApps via ConfigRecord.

4. ClientApp (running inside a container started by Armadillo)
   reads ARMADILLO_URL from its environment variable, sanitizes
   it, and looks up its matching token from the ConfigRecord.

5. ClientApp calls POST /flower/push-data on Armadillo with
   the OIDC token, project, resource, and container name.

6. Armadillo (server-side):
   a. Validates OIDC token, checks project authorization
   b. Reads data from storage
   c. Pushes data into container via docker exec

7. ClientApp helper (load_data):
   a. Waits for file to appear
   b. Reads file into bytes
   c. Deletes file immediately
   d. Returns raw bytes

8. Researcher code parses bytes into the format they need
   (file is gone, data in memory only)

9. Training proceeds. ClientApp exits. Memory freed by OS.
```

---

## Security Properties

| Property | DataSHIELD | Flower |
|----------|------------|--------|
| **Authentication** | OIDC via Spring Security | OIDC via Spring Security |
| **Authorization** | `ROLE_<PROJECT>_RESEARCHER` | `ROLE_<PROJECT>_RESEARCHER` |
| **Data push mechanism** | Rserve protocol | Docker exec |
| **File lifetime** | Milliseconds | Milliseconds |
| **Credentials in container?** | No | No |
| **Who controls file deletion?** | Armadillo (via Rserve) | Our helper library (`load_data()`) |

---

## Token Routing

Tokens are routed using sanitized URLs as keys. The researcher authenticates to each Armadillo server, and the authenticate CLI derives a config-safe key from each URL using `sanitize_url()` (strips scheme, lowercases, replaces non-alphanumeric chars with hyphens).

```
flower-nodes.yaml          Token file                  pyproject.toml
(researcher config)        (generated)                 (app config)

urls:                      token-armadillo-demo-       [tool.flwr.app.config]
  - "https://armadillo-      molgenis-net: "eyJ..."    token-armadillo-demo-
     demo.molgenis.net"    url-armadillo-demo-            molgenis-net = ""
                             molgenis-net: "https://
                             armadillo-demo..."
```

On the container side, Armadillo injects the `ARMADILLO_URL` environment variable when starting the superexec container. The Python helpers read this to match the correct token:

- `get_node_url()` — reads `ARMADILLO_URL` from the environment
- `get_node_token(msg)` — sanitizes the URL, looks up `token-{key}` from the ConfigRecord

---

## Components

### 1. Armadillo: Container Management (Java — `molgenis-service-armadillo`)

Manages Flower container lifecycle:
- **FlowerSupernodeContainerConfig** — supernode with TLS certificates, trusted entities, and Docker args (e.g. `--superlink`)
- **FlowerSuperexecContainerConfig** — clientapp container where researcher code runs
- **DockerService** — creates containers on `flower-network`, injects `ARMADILLO_CONTAINER_NAME` and `ARMADILLO_URL` env vars into superexec containers, mounts certs into supernodes

### 2. Armadillo: Push-Data Endpoint (Java — `molgenis-service-armadillo`)

`POST /flower/push-data` endpoint that:
- Accepts `{ project, resource, containerName }` plus an OIDC Bearer token
- Checks authorization via `@PreAuthorize` (`ROLE_SU` or `ROLE_{PROJECT}_RESEARCHER`)
- Reads data from storage using `armadilloStorage.loadObject()`
- Copies data into the container via Docker API (`copyArchiveToContainerCmd`)
- Returns 204 No Content

### 3. Python Package: `molgenis-flwr-armadillo`

**CLI tools:**
- `armadillo-flwr-authenticate` — authenticates to each Armadillo URL via OIDC device flow, saves tokens
- `armadillo-flwr-run` — loads tokens and injects them into `flwr run --run-config`
- `armadillo-flwr-resources` — lists accessible projects and resources on each Armadillo

**Helper functions (for use in Flower apps):**
- `extract_tokens(context)` — collects `token-*` keys from run_config for the server to forward
- `get_node_url()` — reads `ARMADILLO_URL` env var
- `get_node_token(msg)` — matches this node's token from the ConfigRecord
- `sanitize_url(url)` — converts URL to a config-safe key
- `load_data(url, token, project, resource)` — requests data push, reads file, deletes it, returns bytes
- `list_projects(url, token)` — lists accessible projects
- `list_resources(url, token, project)` — lists resources in a project
- `check_access(url, token, project, resources)` — verifies access before training

---

## Implementation Stages

### Stage 1: Token Routing

Pass OIDC tokens via Flower's run_config. Each ClientApp receives all tokens and picks its own by matching the sanitized `ARMADILLO_URL` from its environment.

### Stage 2: Push-Data Endpoint (Armadillo)

`POST /flower/push-data` endpoint. Reuses existing auth, storage, and Docker client. Data pushed into container via `docker exec` / Docker API tar copy.

### Stage 3: Python Data Helpers (molgenis-flwr-armadillo)

`load_data()` helper and supporting functions. End-to-end flow: authenticate → submit job → data pushed → model trained.

### Stage 4: Differential Privacy

Client-side clipping on model parameters. Clients clip updates before sending, server adds noise after aggregation.

### Stage 5: Per-Container Permissions

Extend Armadillo's permission model so users have access to specific containers, not just projects. Currently `User → Project → [all containers]`, target is `User → Project → Container(s)`.

#### Why Per-Container Matters

**Reusable across DataSHIELD and Flower.** Container-level permissions are not Flower-specific — they apply equally to DataSHIELD profiles. Currently any researcher with project access can select any DataSHIELD profile (`POST /select-profile` has no container authorization) and any Flower container (`POST /flower/push-data` checks the project but not the container name). Per-container permissions close this gap for both.

**Controls whether a researcher can use Flower at all.** A Flower supernode is a container. If a researcher doesn't have permission for any Flower container, they effectively can't use Flower on that Armadillo instance — even if they have project access. This gives admins a clean way to enable or disable Flower for specific researchers without changing project permissions.

#### Enforcement Points

Both DataSHIELD and Flower already pass the container name through their request path, so enforcement requires minimal plumbing:

| Use case | Where enforced | Current check | Added check |
|----------|---------------|---------------|-------------|
| DataSHIELD profile selection | `DataController.selectContainer()` | Authenticated user only | + user has permission for container |
| Flower data push | `FlowerDataService.pushData()` | `ROLE_{PROJECT}_RESEARCHER` | + user has permission for `containerName` |

#### Container Self-Identification Vulnerability

**Problem:** The current `POST /flower/push-data` endpoint trusts the `containerName` field in the request body. The clientapp reads `ARMADILLO_CONTAINER_NAME` from its own environment and sends it to Armadillo. But a malicious app running inside the container could send a different container name, bypassing per-container permissions or pushing data into another container.

**Fix: Server-side container identity resolution.** Remove `containerName` from the request body entirely. Instead, Armadillo resolves the calling container from the source IP of the HTTP request.

**How it works:**

1. The clientapp calls `POST /flower/push-data` with only `project` and `resource` (no `containerName`)
2. `FlowerController.pushData()` reads the source IP from `HttpServletRequest.getRemoteAddr()`
3. Armadillo resolves the IP to a container name by inspecting the Docker network:
   ```java
   // Docker Java API equivalent of: docker network inspect flower-network
   dockerClient.inspectNetworkCmd()
       .withNetworkId("flower-network")
       .exec()
       .getContainers()  // Map<String, ContainerNetworkConfig>
       // find the entry whose IPv4Address matches remoteAddr
   ```
4. If no container matches the source IP → 403 Forbidden (request didn't come from a managed container)
5. The resolved container name is used for the `docker exec` push and for per-container permission checks

**Why this is reliable:** Flower containers already run on a dedicated Docker bridge network (`flower-network`). On a bridge network, each container gets a stable IP that's visible to Armadillo via the Docker API. The IP→container mapping is authoritative — Docker manages it, not the container.

**Changes required:**

| Component | Change |
|-----------|--------|
| `PushDataRequest` | Remove `containerName` field |
| `FlowerController.pushData()` | Inject `HttpServletRequest`, pass `request.getRemoteAddr()` to service |
| `FlowerDataService.pushData()` | Accept source IP instead of container name, resolve via Docker API |
| `FlowerDockerService` | New method: `resolveContainerByIp(String networkName, String ip)` |
| `helpers.py` (`load_data()`) | Remove `containerName` from the request body, remove `ARMADILLO_CONTAINER_NAME` env var dependency |
| `DockerService.configureEnv()` | No longer needs to set `ARMADILLO_CONTAINER_NAME` |

### Stage 6: Result Storage

Allow researchers to upload model results to Armadillo and retrieve them later.

---

## Manual Review Checklist

Researcher-submitted Flower app code should be reviewed for:

- [ ] Uses `load_data()` to get data
- [ ] Does not access the data directory directly
- [ ] No hardcoded file paths
- [ ] No exfiltration of raw bytes

---

## Open Questions

1. **Server-side evaluation:** ServerApp needs test data for `global_evaluate()`. Options: (a) client-side evaluation only, (b) push data to the ServerApp container too.

2. **OIDC token refresh:** If access token expires during long training, refresh token is available. Could add automatic refresh to Python helpers.
