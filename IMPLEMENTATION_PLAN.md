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
| **2. Researcher triggers** | `datashield.assign.table()` | Submits Flower job with token, project, and resource in run_config |
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
1. User authenticates (OIDC) and submits a Flower job

2. Flower routes the job to the ClientApp subprocess
   (OIDC token travels inside Flower's ConfigRecord)

3. ClientApp calls Armadillo to push data
   (POST /flower/push-data with OIDC token, project, and resource)

4. Armadillo (server-side):
   a. Validates OIDC token, checks project authorization
   b. Reads data from storage
   c. Pushes data into container via docker exec

5. ClientApp helper (load_data):
   a. Waits for file to appear
   b. Reads file into bytes
   c. Deletes file immediately
   d. Returns raw bytes

6. Researcher code parses bytes into the format they need
   (file is gone, data in memory only)

7. Training proceeds. ClientApp exits. Memory freed by OS.
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

## Components to Build

### 1. Armadillo: Push-Data Endpoint (Java)

A new `POST /flower/push-data` endpoint that:
- Accepts project and resource identifiers plus an OIDC token
- Uses existing Spring Security and `@PreAuthorize` for authentication/authorization
- Reads data from storage using existing `armadilloStorage.loadObject()`
- Pushes data into the requesting container via `docker exec`

### 2. Python Helper: `load_data()` (molgenis-flwr-armadillo)

A function that:
- Calls Armadillo's push-data endpoint with the OIDC token from the Flower context
- Waits for the file to appear in the container
- Reads the file into memory as raw bytes
- Deletes the file immediately
- Returns the bytes for the researcher to parse in any format they need

### 3. Researcher's ClientApp

The researcher calls `load_data(context)` to get raw bytes, then parses them with whatever library they need (pandas, torch, numpy, PIL, etc.). The file is already gone by the time their code runs.

---

## Implementation Stages

### Stage 1: Token Routing POC ✅

Pass token strings via Flower's run_config and verify each client receives its correct token. Complete.

### Stage 2: Push-Data Endpoint (Armadillo)

New `POST /flower/push-data` endpoint. Reuses existing auth, storage, and Docker client. Main new logic is the `docker exec` data push and container ID resolution.

### Stage 3: Python Data Helpers (molgenis-flwr-armadillo)

`load_data(context)` helper and updated example app. End-to-end test: authenticate → submit job → data pushed → model trained.

### Stage 4: FAB Signing + Trusted Key Management

Flower Application Bundles (FABs) are digitally signed by data stewards so that verified supernodes can reject unsigned or untrusted code before execution.

**Signing side (molgenis-flwr-armadillo) — already implemented:**
- `molgenis-flwr-keygen` — generates Ed25519 keypair
- `molgenis-flwr-sign` — signs a Flower app into a `.sfab` file
- `supernode_verify.py` — verified supernode wrapper that patches Flower to reject unsigned FABs

**Trusted key management (Armadillo) — to build:**

In production, Armadillo manages which signing keys are trusted. The flow:

1. Data steward generates a keypair and shares their public key with the server admin
2. Admin uploads the public key to Armadillo via API or UI
3. Armadillo stores the key (with its derived key ID) alongside other config
4. When starting a verified supernode, Armadillo generates `trusted-entities.yaml` from all registered keys and mounts it into the container

Armadillo changes needed:
- Storage for trusted signing keys (e.g. a JSON file similar to `access.json`, or a new config section)
- API endpoints to add/remove/list trusted keys (`POST /flower/trusted-keys`, `DELETE /flower/trusted-keys/{keyId}`, `GET /flower/trusted-keys`)
- UI page to manage trusted keys
- Container startup logic: generate `trusted-entities.yaml` from stored keys and mount it into verified supernode containers

### Stage 5: Differential Privacy

Client-side clipping on model parameters. Clients clip updates before sending, server adds noise after aggregation.

### Stage 6: Per-Container Permissions

Extend Armadillo's permission model so users have access to specific containers, not just projects. Currently `User → Project → [all containers]`, target is `User → Project → Container(s)`.

### Stage 7: Result Storage

Allow researchers to upload model results to Armadillo and retrieve them later.

---

## Manual Review Checklist

Since file deletion is handled by our helper library, researcher-submitted code should be reviewed for:

- [ ] Uses `load_data(context)` to get data
- [ ] Does not access the data directory directly
- [ ] No hardcoded file paths
- [ ] No exfiltration of raw bytes

---

## Estimated Effort

| Component | Complexity | Notes |
|-----------|------------|-------|
| Push-data endpoint (Java) | Low | Single endpoint, reuses existing auth and storage |
| Docker exec push logic (Java) | Low | Reuses existing Docker client |
| `load_data()` helper (Python) | Low | ~50 lines |
| Docker image changes | Minimal | Ensure data directory exists |

This reuses existing Spring Security, storage service, and Docker client infrastructure.

---

## Progress Checklist

### Infrastructure
- [x] Package structure (`molgenis_flwr_armadillo`)
- [x] CLI: `molgenis-flwr-authenticate`
- [x] CLI: `molgenis-flwr-run`
- [x] Token routing helpers (`extract_tokens`, `get_node_token`)
- [ ] CLI: `molgenis-flwr-tables` (list available data)
- [ ] Error handling for Armadillo requests

### Stage 1: Token Routing ✅
### Stage 2: Push-Data Endpoint
- [ ] `FlowerController` with push-data endpoint
- [ ] Docker exec data push logic
- [ ] Container ID resolution
- [ ] Integration test

### Stage 3: Python Data Helpers
- [ ] `load_data()` implementation
- [ ] Example app updated
- [ ] End-to-end verified

### Stage 4: FAB Signing + Trusted Key Management
- [x] `molgenis-flwr-keygen` CLI
- [x] `molgenis-flwr-sign` CLI
- [x] Verified supernode wrapper (`supernode_verify.py`)
- [ ] Armadillo: trusted key storage
- [ ] Armadillo: API endpoints for key management
- [ ] Armadillo: UI for key management
- [ ] Armadillo: auto-generate `trusted-entities.yaml` on supernode startup

### Stage 5: Differential Privacy
- [ ] DP strategy wrapper + client clipping

### Stage 6: Per-Container Permissions
- [ ] Permission model, authorization, API, UI, migration

### Stage 7: Result Storage
- [ ] Upload/download/list endpoints + CLI tool

---

## Open Questions

1. **Container ID resolution:** How does Armadillo know which container to `docker exec` into? Options: (a) pass container ID in the request, (b) Armadillo tracks which containers it started and maps by identifier.

2. **Server-side evaluation:** ServerApp needs test data for `global_evaluate()`. Options: (a) client-side evaluation only, (b) push data to the ServerApp container too.

3. **OIDC token refresh:** If access token expires during long training, refresh token is available. Could add automatic refresh to Python helpers.

4. **Armadillo URL from container:** `host.docker.internal` works on Docker Desktop; on Linux production, may need the Docker bridge gateway IP or an env var set by Armadillo when creating the container.
