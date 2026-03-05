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

### Stage 4: FAB Review and Signing Workflow

Flower FABs contain arbitrary Python that executes on nodes with access to data. Flower has no local FAB signing — their signing is coupled to their hosted Platform. We've built `molgenis-flwr-sign`, `molgenis-flwr-keygen`, and `supernode_verify.py` to fill this gap. This stage adds the **workflow** around these tools, inspired by vantage6's algorithm store (multi-reviewer approval before algorithms run on nodes).

**Signing side (molgenis-flwr-armadillo) — already implemented:**
- `molgenis-flwr-keygen` — generates Ed25519 keypair
- `molgenis-flwr-sign` — signs a Flower app into a `.sfab` file
- `molgenis-flwr-run` — submits a signed FAB to a SuperLink
- `supernode_verify.py` — verified supernode wrapper that patches Flower to reject unsigned FABs

#### Stage 4A: PoC (Manual Signing)

Everything done by hand using the existing CLI tools. No new code — just documentation and an end-to-end test proving the chain works.

**Workflow:**

```
Researcher               Data manager(s)              Node operator
    |                          |                            |
    | 1. Writes Flower app     |                            |
    |    (client_app.py etc)   |                            |
    |                          |                            |
    | 2. Sends app directory   |                            |
    |    (zip/tar/git) ------->|                            |
    |                          |                            |
    |              3. Reviews code manually                  |
    |              4. If approved:                           |
    |                 molgenis-flwr-sign \                   |
    |                   --app-dir <app> \                    |
    |                   --private-key consortium.key \       |
    |                   --output study.sfab                  |
    |                          |                            |
    | 5. Receives .sfab <------|                            |
    |                          |                            |
    | 6. molgenis-flwr-run \   |                            |
    |      --signed-fab study.sfab \                        |
    |      --federation-address host:9093                   |
    |                          |                            |
    |                          |    (SuperNode verifies     |
    |                          |     signature, runs FAB)   |
```

**Setup (one-time):**
1. Generate consortium keypair: `molgenis-flwr-keygen --name consortium`
2. Configure each SuperNode with `trusted-entities.yaml` containing the public key
3. Deploy `molgenis/verified-supernode` image instead of `flwr/supernode`

**Deliverables:**
- Documentation: guide explaining the manual workflow
- E2E test: extend `test-flower-containers.sh` to cover signing scenarios

**Limitations:**
- Data manager must manually receive, review, and sign each app
- Private key lives on the data manager's laptop
- No structured review process — just "someone looked at it"
- Public key distribution to nodes is manual
- Multi-institution approval is informal (no enforced policy)

#### Stage 4B: GitHub Review + CI Signing (`molgenis-flwr-apps` repo)

Automates the manual workflow with a GitHub-based review process and CI signing. A new repo where researchers submit code as PRs. CI signs on merge after multi-institution approval.

**Repo structure:**

```
molgenis-flwr-apps/
├── .github/
│   ├── workflows/
│   │   ├── review.yml          # PR: lint + build check
│   │   └── sign.yml            # post-merge: sign + release
│   ├── CODEOWNERS              # require approval from each institution
│   └── PULL_REQUEST_TEMPLATE.md
├── public-keys/
│   └── consortium.pub
├── apps/
│   └── <study-name>/
│       ├── pyproject.toml
│       ├── STUDY_INFO.md
│       └── <app_package>/
│           ├── __init__.py
│           ├── client_app.py
│           └── server_app.py
├── CONTRIBUTING.md
└── README.md
```

**CODEOWNERS — multi-institution approval:**

```
apps/ @org/institution-a @org/institution-b @org/institution-c ...
```

Combined with branch protection: "Require review from Code Owners" + required approvals matching the number of institutions.

**review.yml — build check on PR:**

Triggered on PRs to `main` touching `apps/**`:
1. Checks `pyproject.toml` and `STUDY_INFO.md` exist
2. Checks app size < 10MB
3. Lints with ruff
4. Builds FAB (dry run, no signing) to verify it's well-formed

**sign.yml — sign on merge:**

Triggered on push to `main` touching `apps/**`. Runs in a protected GitHub Environment (`signing`) which requires manual deployment approval and holds the `FAB_SIGNING_KEY` secret.

1. Detect which study directories changed
2. Write signing key from secret to temp file
3. `molgenis-flwr-sign --app-dir <dir> --private-key <key> --output <name>.sfab`
4. Shred key file (`always()` step)
5. Create GitHub Release with `.sfab` attached
6. Post commit comment with download link

**Researcher gets the signed FAB:**
- GitHub Release notification (researcher watches the repo)
- Commit comment with direct link
- Downloads `.sfab`, runs `molgenis-flwr-run --signed-fab study.sfab --federation-address <host:port>`

**PR template:**

```markdown
## Study Information
- **Study name:**
- **PI:**
- **Institution:**
- **Armadillo project:**
- **Resource(s) accessed:**

## What does this app compute?

## Checklist
- [ ] STUDY_INFO.md is present and complete
- [ ] App uses load_data(context) from molgenis_flwr_armadillo.helpers
- [ ] No hardcoded file paths or direct filesystem access
- [ ] pyproject.toml version incremented from any prior submission
- [ ] Dependencies are necessary and minimal
```

**GitHub setup (one-time):**
1. Create `molgenis-flwr-apps` repo
2. Consortium lead generates keypair: `molgenis-flwr-keygen --name consortium`
3. Commit `consortium.pub` to `public-keys/`
4. Create GitHub Environment `signing` with required reviewer + secret `FAB_SIGNING_KEY`
5. Configure branch protection on `main` (require approvals, CODEOWNERS, status checks)
6. Create GitHub teams per institution, add data managers
7. Add researchers as collaborators with Write access

#### Stage 4C: Armadillo Trusted Key API (`molgenis-service-armadillo`)

Eliminates manual key distribution to nodes. Data managers upload public keys through the Armadillo admin UI.

**New endpoints:**

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/flower/trusted-keys` | Upload a public key (PEM body + optional label) |
| `GET` | `/flower/trusted-keys` | List registered keys (key_id, label, created_at) |
| `DELETE` | `/flower/trusted-keys/{keyId}` | Remove a key |

**Storage:** JSON file similar to `access.json`, or a new config section. Each entry stores:
- `keyId` — derived from `derive_key_id(public_key)` (e.g. `fpk_3a7b9c2d`)
- `publicKeyPem` — PEM-encoded Ed25519 public key
- `label` — human-readable name (e.g. "consortium-2025")
- `createdAt` — timestamp

**UI:** Admin page to manage trusted keys — same pattern as DataSHIELD profile management. List view with add/delete actions.

**SuperNode startup integration:**

When Armadillo starts a verified SuperNode container, it:
1. Reads all registered trusted keys from storage
2. Generates `trusted-entities.yaml` (YAML: `{key_id: pem_string, ...}`)
3. Mounts it into the container at `/config/trusted-entities.yaml`

This replaces the manual `trusted-entities.yaml` creation from Stage 4A.

**Full chain (Stage 4B + 4C combined):**

```
Consortium lead                 GitHub                  Each institution
      |                            |                          |
      | molgenis-flwr-keygen       |                          |
      | → consortium.key, .pub     |                          |
      |                            |                          |
      | private key -------------->| (Environment secret)     |
      | commits public key ------->| (public-keys/)           |
      |                            |                          |
      |                            |  admin downloads .pub    |
      |                            |------------------------->|
      |                            |                          |
      |                            |  POST /flower/trusted-keys
      |                            |  (uploads via Armadillo UI)
      |                            |                          |
      |                            |  Armadillo auto-generates|
      |                            |  trusted-entities.yaml   |
      |                            |  into verified SuperNode |

Researcher                     GitHub                  SuperNode
      |                            |                       |
      | opens PR with app code --->|                       |
      |                            | review.yml runs       |
      |    all institutions approve PR                     |
      |                            | PR merged             |
      |                            | sign.yml runs         |
      |                            |  (env approval)       |
      |                            |  signs FAB            |
      |                            |  creates Release      |
      | downloads .sfab <----------|                       |
      |                            |                       |
      | molgenis-flwr-run ---------|---------------------->|
      |   --signed-fab study.sfab  |   verifies signature  |
      |                            |   runs FAB            |
```

### Stage 5: Differential Privacy

Client-side clipping on model parameters. Clients clip updates before sending, server adds noise after aggregation.

### Stage 6: Per-Container Permissions

Extend Armadillo's permission model so users have access to specific containers, not just projects. Currently `User → Project → [all containers]`, target is `User → Project → Container(s)`.

#### Why Per-Container Matters

**Reusable across DataSHIELD and Flower.** Container-level permissions are not Flower-specific — they apply equally to DataSHIELD profiles. Currently any researcher with project access can select any DataSHIELD profile (`POST /select-profile` has no container authorization) and any Flower container (`POST /flower/push-data` checks the project but not the container name). Per-container permissions close this gap for both.

**Controls whether a researcher can use Flower at all.** A Flower supernode is a container. If a researcher doesn't have permission for any Flower container, they effectively can't use Flower on that Armadillo instance — even if they have project access. This gives admins a clean way to enable or disable Flower for specific researchers without changing project permissions.

#### Enforcement Points

Both DataSHIELD and Flower already pass the container name through their request path, so enforcement requires minimal plumbing:

| Use case | Where enforced | Current check | Added check |
|----------|---------------|---------------|-------------|
| DataSHIELD profile selection | `DataController.selectContainer()` | Authenticated user only | + `ROLE_{PROJECT}_{CONTAINER}_USER` or service-level check |
| Flower data push | `FlowerDataService.pushData()` | `ROLE_{PROJECT}_RESEARCHER` | + user has permission for `containerName` |

**Implementation options:**

1. **Role-based (Spring Security).** Extend `getAuthoritiesForEmail()` in `AccessService` to emit `ROLE_{PROJECT}_{CONTAINER}_RESEARCHER` roles. Enforcement via `@PreAuthorize`. Clean but produces many roles in multi-container setups.

2. **Service-level check (simpler).** Add a `ContainerPermissionService` that checks a permissions set, called explicitly from the controller/service methods. Avoids role proliferation and is easier to reason about. Follows the same pattern as `AccessService.getPermissionsForEmail()`.

Option 2 is likely better — it keeps the role model simple (`ROLE_SU` + `ROLE_{PROJECT}_RESEARCHER`) and adds container checks as an additional layer.

#### Container Self-Identification Vulnerability

**Problem:** The current `POST /flower/push-data` endpoint trusts the `containerName` field in the request body. The clientapp reads `ARMADILLO_CONTAINER_NAME` from its own environment and sends it to Armadillo. But a malicious FAB running inside the container could send a different container name, bypassing per-container permissions or pushing data into another container.

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

**Changes required:**

| Component | Change |
|-----------|--------|
| `PushDataRequest` | Remove `containerName` field |
| `FlowerController.pushData()` | Inject `HttpServletRequest`, pass `request.getRemoteAddr()` to service |
| `FlowerDataService.pushData()` | Accept source IP instead of container name, resolve via Docker API |
| `FlowerDockerService` | New method: `resolveContainerByIp(String networkName, String ip)` |
| `helpers.py` (`load_data()`) | Remove `containerName` from the request body, remove `ARMADILLO_CONTAINER_NAME` env var dependency |
| `DockerService.configureEnv()` | No longer needs to set `ARMADILLO_CONTAINER_NAME` |

**Why this is reliable:** Flower containers already run on a dedicated Docker bridge network (`flower-network`). On a bridge network, each container gets a stable IP that's visible to Armadillo via the Docker API. The IP→container mapping is authoritative — Docker manages it, not the container.

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

### Stage 4A: FAB Signing PoC (Manual)
- [x] `molgenis-flwr-keygen` CLI
- [x] `molgenis-flwr-sign` CLI
- [x] `molgenis-flwr-run` CLI (signed FAB submission)
- [x] Verified supernode wrapper (`supernode_verify.py`)
- [ ] Documentation: manual signing workflow guide
- [ ] E2E test: `test-flower-containers.sh`
- [ ] Docker Compose: verified supernode setup

### Stage 4B: GitHub Review + CI Signing (`molgenis-flwr-apps`)
- [ ] Create `molgenis-flwr-apps` repo with apps/ structure
- [ ] `review.yml` workflow (lint + build check on PR)
- [ ] `sign.yml` workflow (sign + release on merge)
- [ ] CODEOWNERS with multi-institution approval
- [ ] PR template with study info checklist
- [ ] GitHub Environment `signing` with `FAB_SIGNING_KEY` secret
- [ ] Branch protection rules on `main`

### Stage 4C: Armadillo Trusted Key API (`molgenis-service-armadillo`)
- [ ] Trusted key storage (JSON config)
- [ ] `POST /flower/trusted-keys` endpoint
- [ ] `GET /flower/trusted-keys` endpoint
- [ ] `DELETE /flower/trusted-keys/{keyId}` endpoint
- [ ] Admin UI for key management
- [ ] Auto-generate `trusted-entities.yaml` on verified SuperNode startup

### Stage 5: Differential Privacy
- [ ] DP strategy wrapper + client clipping


### Stage 6: Per-User, Per-Project, Per-Container, Per-App Permissions

Extend Armadillo's permission model to support fine-grained Flower authorization. Currently permissions are `User → Project` (a researcher can access all data in a project). The target is `User → Project → App → Container`, so admins control exactly which researchers can run which approved apps on which nodes.

#### Data Model

**FlowerApp** — a registered Flower application (managed by admin/data steward):
- `name` — human-readable identifier (e.g. "pytorch-cifar10-v2")
- `signingKeyId` — derived key ID (e.g. `fpk_3a7b9c2d`), links to Stage 4C trusted key
- `fabHash` — optional SHA-256 of the approved FAB content, for hash-based verification as an alternative to key-based signing
- `description` — what the app computes
- `createdAt` — timestamp

**FlowerAppPermission** — extends the existing permission model:
- `email` — researcher
- `project` — which project's data the app can access
- `appName` — which registered FlowerApp
- `containerName` — optional, restricts to specific supernode(s). If null, app can run on any supernode in the project.

This follows the same pattern as `ProjectPermission` (email + project), adding app and container dimensions.

#### How It Fits Into the Existing Auth Flow

Current auth check (data loading):
```
ClientApp calls POST /flower/push-data with OIDC token
  → Spring Security validates token
  → @PreAuthorize checks ROLE_{PROJECT}_RESEARCHER
  → Data pushed into container
```

Extended auth check:
```
ClientApp calls POST /flower/push-data with OIDC token + app metadata
  → Spring Security validates token
  → Check: does this user have FlowerAppPermission for (project, app, container)?
  → If yes: data pushed into container
  → If no: 403 Forbidden
```

The FAB's identity (app name or hash) would need to be available at data-load time. Options:
1. The supernode sets an env var (e.g. `FLOWER_APP_NAME`) when it verifies and accepts a FAB, which `load_data()` includes in the push-data request
2. The run_config includes the app name, set by the researcher or by `molgenis-flwr-run`

#### Supernode Integration

The supernode currently checks FAB signatures against a local trusted-entities file. With registered FlowerApps in Armadillo:

1. At startup, supernode calls `GET /flower/trusted-keys` (Stage 4C) to fetch trusted signing keys
2. On FAB verification, supernode can additionally call `GET /flower/apps/{keyId}` to resolve which app this FAB belongs to
3. The app identity propagates to the clientapp environment for the data-load auth check

This means the supernode doesn't need any local configuration beyond the Armadillo URL — all trust decisions are centralized in Armadillo.

#### API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/flower/apps` | List registered Flower apps |
| `POST` | `/flower/apps` | Register a new app (name, signing key, optional FAB hash) |
| `PUT` | `/flower/apps/{name}` | Update app (e.g. new FAB hash for a new version) |
| `DELETE` | `/flower/apps/{name}` | Remove an app |
| `GET` | `/flower/apps/{name}/permissions` | List permissions for an app |
| `POST` | `/flower/apps/{name}/permissions` | Grant: user + project + optional container |
| `DELETE` | `/flower/apps/{name}/permissions/{id}` | Revoke a permission |

These follow the same patterns as the existing `/access/` endpoints.

#### UI

Admin page "Flower Apps" (same pattern as Profiles page):
- List view: registered apps with name, signing key, description
- Detail view: permissions table (user × project × container)
- Add/edit/delete actions

#### Storage

New JSON config file (e.g. `flower-apps.json`) following the same pattern as `access.json`:
```json
{
  "apps": {
    "pytorch-cifar10-v2": {
      "signingKeyId": "fpk_3a7b9c2d",
      "fabHash": "sha256:abc123...",
      "description": "CIFAR-10 federated training with PyTorch",
      "createdAt": "2026-03-01T12:00:00Z"
    }
  },
  "permissions": [
    {
      "email": "researcher@institution.org",
      "project": "test-flower",
      "appName": "pytorch-cifar10-v2",
      "containerName": null
    }
  ]
}
```

#### Checklist

- [ ] `FlowerApp` model and `FlowerAppPermission` model
- [ ] `FlowerAppService` (CRUD + permission management)
- [ ] Storage: `flower-apps.json` loader/saver
- [ ] REST endpoints for app and permission management
- [ ] Extend `POST /flower/push-data` to check app-level permissions
- [ ] Supernode: resolve app identity from FAB signing key
- [ ] Admin UI: Flower Apps page
- [ ] Migration: existing setups continue to work without app permissions (backwards-compatible)

### Stage 7: Result Storage
- [ ] Upload/download/list endpoints + CLI tool

---

## Existing Code Reused (no changes needed)

| File | Used in |
|------|---------|
| `sign_cli.py` (`molgenis-flwr-sign`) | Stage 4A manual, Stage 4B CI |
| `keygen.py` (`molgenis-flwr-keygen`) | Stage 4A + 4B key generation |
| `signing.py` (`sign_fab`, `derive_key_id`) | Core crypto |
| `run.py` (`molgenis-flwr-run`) | Stage 4A + 4B FAB submission |
| `supernode_verify.py` | Node-side verification |

---

## Open Questions

1. **Container ID resolution:** How does Armadillo know which container to `docker exec` into? Options: (a) pass container ID in the request, (b) Armadillo tracks which containers it started and maps by identifier.

2. **Server-side evaluation:** ServerApp needs test data for `global_evaluate()`. Options: (a) client-side evaluation only, (b) push data to the ServerApp container too.

3. **OIDC token refresh:** If access token expires during long training, refresh token is available. Could add automatic refresh to Python helpers.

4. **Armadillo URL from container:** `host.docker.internal` works on Docker Desktop; on Linux production, may need the Docker bridge gateway IP or an env var set by Armadillo when creating the container.
