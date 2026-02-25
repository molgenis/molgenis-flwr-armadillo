# Secure Data Access for Flower Clients

## Problem

Flower clients (running in Docker containers on Armadillo) need to download training data
from Armadillo storage, but only for projects the user has permission to access. The user
writes the code that runs inside the container, so any credential placed in the container
is readable by the user's code. We need a design where even if the user extracts the
token, they cannot use it to download data directly.

## Current State

### molgenis-flwr-armadillo (branch `epic/flower`)

- `authenticate.py` — user authenticates via OIDC device flow, gets access tokens
- `run.py` — loads tokens from `/tmp/flwr_tokens.json`, passes via `flwr run --run-config`
- `helpers.py` — `extract_tokens()` and `get_node_token()` route tokens through Flower's
  message protocol: server_app extracts all tokens from run_config, puts them in
  ConfigRecord, Flower sends ConfigRecord to each client, client_app extracts its own
  token using its node-name
- The OIDC token arrives inside the ClientApp subprocess via Flower's message protocol
- **No data download from Armadillo is implemented yet** — the example still loads
  CIFAR-10 from HuggingFace

### molgenis-service-armadillo

- `feat/flower` branch: `DockerService` creates SuperNode and ClientApp containers on a
  Docker bridge network (`flower-network`), passing command args and env vars
- `epic/flower` branch: merged from master, no Flower-specific changes yet
- `ResourceTokenService` — generates RSA-signed internal JWTs with configurable TTL
  (default 300s). Used today for DataShield resource loading. Keys are generated
  in-memory at startup (2048-bit RSA).
- `JwtDecoderConfig` — dual decoder: tries internal decoder first (RSA public key,
  validates issuer = `"http://armadillo-internal"`), falls back to external decoder
  (Keycloak OIDC). No changes needed — this already handles both token types.
- `StorageController` — `/rawfiles` endpoint validates internal tokens by checking
  issuer, resource_project, and resource_object claims
- `ArmadilloStorageService` — `@PreAuthorize` on all data access methods, checks
  `ROLE_SU` or `ROLE_{PROJECT}_RESEARCHER`

### How the OIDC Token Reaches the ClientApp Today

```
1. User runs: molgenis-flwr-authenticate
   → OIDC device flow (browser) against each Armadillo node
   → Tokens saved to /tmp/flwr_tokens.json as {"token-nodename": "eyJ..."}

2. User runs: molgenis-flwr-run --app-dir examples/quickstart-pytorch
   → Loads tokens from file
   → Executes: flwr run . --run-config "token-demo=eyJ... token-localhost=eyJ..."

3. Flower routes the job:
   → SuperLink receives run with run_config containing tokens
   → SuperLink sends task to SuperNode
   → SuperNode's SuperExec spawns ClientApp subprocess

4. Inside server_app.py:
   tokens = extract_tokens(context)        # reads token-* keys from run_config
   train_config = ConfigRecord({"lr": lr, **tokens})
   strategy.start(train_config=train_config, ...)
   # Flower sends ConfigRecord to each client via Message

5. Inside client_app.py:
   token = get_node_token(msg, context)
   # Reads context.node_config["node-name"] → "demo"
   # Gets msg.content["config"]["token-demo"] → "eyJ..."
```

The OIDC token is now available in the ClientApp subprocess. Everything below builds
from this point.

---

## Security Model

### Threat Model

The user is a researcher who should be able to run ML models on data but never download
raw data to their own machine. They write the Python code that runs inside the ClientApp
container, so any credential in the container is readable by their code.

### Three Independent Security Layers

**Layer 1: Network isolation (port 9080 bound to Docker bridge)**

Armadillo runs a second HTTP listener on port 9080 that is bound to the Docker bridge
gateway IP (e.g. `172.17.0.1`), not to `0.0.0.0`. This matters because in production,
Armadillo runs as a Java process directly on the host (not in a container) — see
Deployment Context below. By binding to the bridge gateway IP, port 9080 is only
reachable from containers on that Docker network. The user, connecting from their laptop
via Nginx or even via SSH to the host, cannot reach this port because the bridge gateway
IP is a Docker-internal address.

**Deployment context:** Armadillo is deployed as a systemd service running a Java JAR
directly on the host. Nginx acts as a reverse proxy, forwarding HTTPS traffic to
`localhost:8080`. Docker is used for profile containers (DataShield ROCK, Flower
SuperNodes, etc.) but Armadillo itself is not containerised. The architecture is:

```
Internet → Nginx (:443) → localhost:8080 (Armadillo JAR on host)
                                ↕
                          Docker bridge network
                          (flower-network, 172.18.0.0/16)
                                ↕
                    SuperNode / ClientApp containers
```

Because Armadillo runs on the host, port 9080 would normally be accessible to anything
on the host (including SSH users). Binding it to the Docker bridge gateway IP
(`172.18.0.1` for `flower-network`) ensures only containers on that bridge can reach it.
Nginx only proxies to `localhost:8080` and has no knowledge of port 9080.

**Layer 2: OIDC token + @PreAuthorize**

The user's OIDC token (which travels through Flower's run_config → server → client
message chain) is validated against Armadillo's existing permission model. The user must
have `ROLE_{PROJECT}_RESEARCHER` for the requested project. This is the same check
DataShield uses for table and resource access.

**Layer 3: IP-bound internal token**

After validating the OIDC token, Armadillo generates a short-lived internal JWT
(using the existing `ResourceTokenService` RSA key infrastructure) with the requesting
container's TCP source IP baked in as a claim. On every subsequent data request,
Armadillo checks that the request's actual source IP matches the IP in the token.

This works because:
- The IP claim is inside a RSA-signed JWT — it cannot be tampered with
- The source IP comes from the TCP connection — it cannot be spoofed (TCP requires a
  three-way handshake; the attacker would need to receive the SYN-ACK, which goes to
  the real IP)
- Even if the user extracts the token from inside the container, they cannot originate
  a request from the container's Docker bridge IP (e.g. 172.18.0.5) from their laptop

### What Each Layer Blocks

| Attack | Layer 1 (port) | Layer 2 (OIDC) | Layer 3 (IP-bound) |
|--------|:-:|:-:|:-:|
| User curls data endpoint from laptop via Nginx | Blocked | — | — |
| User SSHes to host and curls port 9080 | Blocked (bound to bridge IP) | — | Blocked |
| User accesses project they don't have permission for | — | Blocked | — |
| User extracts token, uses from host machine | Blocked | — | Blocked |
| User extracts token, uses from different container | — | — | Blocked |
| Token intercepted after job completes | — | — | Expired (300s TTL) |

### Additional Protections (Outside This Plan)

- **Differential privacy** (Stage 4 of main implementation plan) — noise added to model
  parameter updates prevents reconstruction of training data from results
- **Network egress restriction** — containers on `flower-network` can be restricted to
  only communicate with Armadillo and the SuperNode, not the internet
- **Short-lived ClientApp process** — Flower's architecture spawns the ClientApp as a
  short-lived subprocess of the SuperExec. When the subprocess exits after completing
  its task, the OS reclaims all process memory. The training data, internal token, and
  any other in-memory state are destroyed. Nothing is written to disk (data is loaded
  via `io.BytesIO` → `torch.load()`, never to a file).

---

## Architecture

### Production Layout

Armadillo runs as a JAR on the host (systemd service), not in Docker. Docker is used
only for profile containers (ROCK, Flower SuperNodes, etc.).

```
Host machine (Ubuntu Linux):
┌──────────────────────────────────────────────────────────────────┐
│                                                                  │
│  Nginx (:443)                                                    │
│    └─ proxy_pass → localhost:8080                                │
│                                                                  │
│  Armadillo JAR (systemd service)                                 │
│    :8080 on localhost     (user-facing API, proxied by Nginx)    │
│    :9080 on 172.18.0.1    (internal data API, Docker bridge only)│
│                                                                  │
│  ┌── flower-network (Docker bridge, subnet 172.18.0.0/16) ────┐ │
│  │                                                              │ │
│  │  SuperNode container (long-running)                          │ │
│  │    172.18.0.2                                                │ │
│  │    contains SuperExec, spawns ClientApp subprocesses         │ │
│  │                                                              │ │
│  │  ClientApp subprocess (short-lived, per task)                │ │
│  │    exchanges OIDC token → IP-bound internal token            │ │
│  │    downloads data from 172.18.0.1:9080                       │ │
│  │    trains model, returns results, exits                      │ │
│  │                                                              │ │
│  └──────────────────────────────────────────────────────────────┘ │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘

User's laptop ──→ Nginx:443 → localhost:8080  ✓  (normal API, UI, auth)
               ──→ 172.18.0.1:9080            ✗  (not routable from outside host)
SSH to host   ──→ localhost:9080              ✗  (not listening on localhost)
              ──→ 172.18.0.1:9080             ✗  (bridge IP not on host's routing table
                                                   unless you're a Docker container)
```

**Why 172.18.0.1 is unreachable from SSH:** The Docker bridge gateway IP (172.18.0.1)
exists on a virtual network interface (`br-xxxx`) created by Docker. While the host
kernel can technically route to it, binding Armadillo's internal port to this specific
interface means it only accepts connections arriving on that interface. A user SSHed into
the host would need to explicitly target this IP, and even then the IP-bound token
provides a second layer of defence (their source IP would be 172.18.0.1, not the
container's IP like 172.18.0.2).

**Note:** On Linux, the host CAN reach Docker bridge IPs directly. The binding to the
bridge gateway IP is not an absolute firewall — it's a strong practical barrier. The
IP-bound token (Layer 3) is the definitive defence against host-level access, since the
host's source IP will never match the container's IP in the token.

### Request Flow

```
1. User authenticates (OIDC) and runs:
     molgenis-flwr-run --run-config "armadillo-project=cifar10 ..."
   (OIDC tokens are injected into run_config automatically)

2. Flower routes the job:
     User → SuperLink → SuperNode → SuperExec → ClientApp subprocess
     (OIDC token travels inside Flower's ConfigRecord)

3. ClientApp extracts its OIDC token and requests an internal token:

     POST http://172.18.0.1:9080/internal/token
     Authorization: Bearer <OIDC_TOKEN>
     Content-Type: application/json
     {"project": "cifar10"}

     Source IP (from TCP connection): 172.18.0.2

4. Armadillo validates the OIDC token and performs the token swap:
     a. JwtDecoderConfig tries internal decoder → fails (not armadillo-internal issuer)
     b. Falls back to external decoder → succeeds (valid Keycloak token)
     c. Spring Security resolves Principal with user's granted authorities
     d. @PreAuthorize checks: does user have ROLE_CIFAR10_RESEARCHER? → yes
     e. Reads source IP from HttpServletRequest.getRemoteAddr() → "172.18.0.2"
     f. Calls ResourceTokenService (or new FlowerTokenService) to generate:
        {
          "iss": "http://armadillo-internal",
          "sub": "researcher@uni.edu",
          "email": "researcher@uni.edu",
          "project": "cifar10",
          "bound_ip": "172.18.0.2",
          "iat": 1740500000,
          "exp": 1740500300
        }
     g. Returns: {"token": "eyJ..."}

5. ClientApp downloads data using the internal token:

     GET http://172.18.0.1:9080/internal/data/cifar10/partitions/partition_0_train.pt
     Authorization: Bearer <INTERNAL_TOKEN>

     Source IP (from TCP connection): 172.18.0.2

6. Armadillo validates the internal token:
     a. JwtDecoderConfig tries internal decoder → succeeds (armadillo-internal issuer,
        valid RSA signature)
     b. FlowerController checks:
        - token.iss == "http://armadillo-internal"  ✓
        - token.project == URL {project}             ✓ ("cifar10")
        - token.bound_ip == request source IP        ✓ ("172.18.0.2")
        - token not expired                          ✓
     c. Loads file from storage, streams bytes back

7. ClientApp loads data into memory:
     data = torch.load(io.BytesIO(response.content), weights_only=True)
     (no file written to disk)

8. Training proceeds. When complete, the ClientApp subprocess exits.
   All process memory (tensors, tokens) is freed by the OS.
```

---

## Implementation

Work is split across two repositories:
- **Armadillo** (`molgenis-service-armadillo`, branch `epic/flower`): Parts 1–4 (Java)
- **Flower wrapper** (`molgenis-flwr-armadillo`, branch `epic/flower`): Parts 5–7 (Python)

---

### Part 1: Internal HTTP Port

**Goal:** Armadillo listens on a second port (9080) bound to the Docker bridge gateway
IP, so only containers on the Docker network can reach it.

**New file: `armadillo/src/main/java/org/molgenis/armadillo/security/InternalPortConfig.java`**

Add a second Tomcat connector bound to the Docker bridge gateway IP. This is the same
pattern Spring Boot uses for management/actuator endpoints on a separate port, but with
an explicit bind address.

```java
@Configuration
public class InternalPortConfig {

    @Value("${armadillo.internal-port:9080}")
    private int internalPort;

    @Value("${armadillo.internal-bind-address:}")
    private String internalBindAddress;

    @Value("${armadillo.docker-run-in-container:false}")
    private boolean runInContainer;

    @Bean
    public WebServerFactoryCustomizer<TomcatServletWebServerFactory> internalConnector() {
        return factory -> {
            if (!runInContainer && (internalBindAddress == null
                    || internalBindAddress.isBlank())) {
                // Host deployment with no bind address — don't start internal port.
                // Keeps the feature off by default for non-Flower deployments.
                return;
            }
            Connector connector = new Connector(
                TomcatServletWebServerFactory.DEFAULT_PROTOCOL);
            connector.setPort(internalPort);
            if (internalBindAddress != null && !internalBindAddress.isBlank()) {
                // Host deployment: bind to Docker bridge gateway IP only
                connector.setProperty("address", internalBindAddress);
            }
            // Container deployment: binds to 0.0.0.0 (default), safe because
            // port 9080 is not published in docker-compose
            factory.addAdditionalTomcatConnectors(connector);
        };
    }
}
```

**Modify: `armadillo/src/main/resources/application.yml`**

```yaml
armadillo:
  internal-port: 9080
  internal-bind-address: ""   # disabled by default; set to Docker bridge gateway IP
```

**Production configuration (on the Armadillo server):**

The data manager configures the internal port in `/etc/armadillo/application.yml`:

```yaml
armadillo:
  internal-port: 9080
  internal-bind-address: "172.18.0.1"   # flower-network bridge gateway IP
```

To find the correct IP, run:
```bash
docker network inspect flower-network --format '{{range .IPAM.Config}}{{.Gateway}}{{end}}'
```

**Why this is safe:** Armadillo runs as a JAR directly on the host (systemd service).
Port 8080 is bound to `localhost` and proxied by Nginx. Port 9080 is bound to
`172.18.0.1` (the Docker bridge gateway), which is a virtual network interface that only
Docker containers on `flower-network` can route to. External users cannot reach it via
Nginx (Nginx only proxies to `localhost:8080`), and SSH users on the host would need to
explicitly target the bridge IP — and even then, the IP-bound token provides a second
layer of defence.

**Note on the bridge gateway IP:** The gateway IP is stable for a given Docker network
as long as the network exists. If the network is recreated, the IP may change. The
`DockerService` already creates `flower-network` — it could also look up the gateway IP
and pass it to the configuration, or the data manager can set it once during setup.

---

### Part 2: Port-Gating Filter

**Goal:** `/internal/*` endpoints only respond on port 9080. All other endpoints only
respond on port 8080. This prevents the user from accessing internal endpoints via the
public port, and prevents container code from accessing other Armadillo APIs via the
internal port.

**New file: `armadillo/src/main/java/org/molgenis/armadillo/security/InternalPortFilter.java`**

```java
@Component
public class InternalPortFilter extends OncePerRequestFilter {

    @Value("${armadillo.internal-port:9080}")
    private int internalPort;

    @Override
    protected void doFilterInternal(
            HttpServletRequest request,
            HttpServletResponse response,
            FilterChain filterChain) throws ServletException, IOException {

        boolean isInternalPath = request.getRequestURI().startsWith("/internal");
        boolean isInternalPort = request.getLocalPort() == internalPort;

        // /internal/* paths must be on the internal port
        if (isInternalPath && !isInternalPort) {
            response.sendError(HttpServletResponse.SC_NOT_FOUND);
            return;
        }

        // Non-internal paths must NOT be on the internal port
        if (!isInternalPath && isInternalPort) {
            response.sendError(HttpServletResponse.SC_NOT_FOUND);
            return;
        }

        filterChain.doFilter(request, response);
    }
}
```

This ensures the internal port is a completely separate surface — it only serves
`/internal/*` and nothing else.

---

### Part 3: Token Exchange and Data Endpoints

**Goal:** Two new endpoints on the internal port:
1. Token exchange: OIDC token in → IP-bound internal token out
2. Data download: internal token in → file bytes out

#### 3a. Flower Token Generation

**Modify: `armadillo/src/main/java/org/molgenis/armadillo/security/ResourceTokenService.java`**

Add a new method for generating Flower tokens. Reuses the existing RSA key pair and
encoder. The existing `generateResourceToken()` method is unchanged — DataShield
resources continue to work as before.

```java
public JwtAuthenticationToken generateFlowerToken(
        Principal principal, String project, String boundIp) {
    String email = principal instanceof JwtAuthenticationToken token
        ? token.getToken().getClaimAsString("email")
        : principal.getName();

    Instant now = Instant.now();
    JwtClaimsSet claims = JwtClaimsSet.builder()
        .issuer(INTERNAL_ISSUER)
        .subject(email)
        .claim("email", email)
        .issuedAt(now)
        .expiresAt(now.plusSeconds(tokenValiditySeconds))
        .claim("project", project)
        .claim("bound_ip", boundIp)
        .build();

    JwsHeader header = JwsHeader.with(SignatureAlgorithm.RS256).build();
    Jwt jwt = jwtEncoder.encode(JwtEncoderParameters.from(header, claims));
    return new JwtAuthenticationToken(jwt);
}
```

The token contains:
- `iss`: `"http://armadillo-internal"` — identifies this as an Armadillo-generated token
- `sub`, `email`: the user who triggered the job (for audit trail)
- `project`: the project this token grants access to
- `bound_ip`: the TCP source IP of the container that requested the token
- `exp`: expiry time (now + 300s by default)

No changes to `JwtDecoderConfig` are needed. The existing dual-decoder already handles
both internal tokens (RSA) and external tokens (Keycloak OIDC).

#### 3b. Controller

**New file: `armadillo/src/main/java/org/molgenis/armadillo/controller/FlowerController.java`**

```java
@RestController
@RequestMapping("/internal")
public class FlowerController {

    private final ResourceTokenService tokenService;
    private final ArmadilloStorageService storageService;

    @Value("${armadillo.internal-port:9080}")
    private int internalPort;

    // --- Token exchange endpoint ---

    @PostMapping("/token")
    @PreAuthorize("hasAnyRole('ROLE_SU', 'ROLE_' + #body.project.toUpperCase() + '_RESEARCHER')")
    public Map<String, String> exchangeToken(
            HttpServletRequest request,
            Principal principal,
            @RequestBody TokenRequest body) {

        String boundIp = request.getRemoteAddr();
        JwtAuthenticationToken internalToken =
            tokenService.generateFlowerToken(principal, body.project(), boundIp);

        return Map.of("token", internalToken.getToken().getTokenValue());
    }

    // --- Data download endpoint ---

    @GetMapping("/data/{project}/{object}")
    public ResponseEntity<InputStreamResource> downloadData(
            HttpServletRequest request,
            Principal principal,
            @PathVariable String project,
            @PathVariable String object) {

        // Principal here is from an internal token (decoded by internal RSA decoder)
        if (!(principal instanceof JwtAuthenticationToken token)) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN,
                "Requires internal token");
        }

        Map<String, Object> claims = token.getTokenAttributes();

        // Validate issuer
        if (!INTERNAL_ISSUER.equals(claims.get("iss"))) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN,
                "Invalid token issuer");
        }

        // Validate project claim matches URL
        if (!project.equals(claims.get("project"))) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN,
                "Token not valid for project: " + project);
        }

        // Validate source IP matches bound_ip claim
        String boundIp = (String) claims.get("bound_ip");
        String actualIp = request.getRemoteAddr();
        if (!actualIp.equals(boundIp)) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN,
                "Token not valid from this address");
        }

        // Load and stream the file
        // Use runAsSystem because the internal token doesn't carry OIDC roles —
        // project access was already verified during the token exchange step
        InputStream data = RunAs.runAsSystem(
            () -> storageService.loadObject(project, object));
        return ResponseEntity.ok()
            .contentType(MediaType.APPLICATION_OCTET_STREAM)
            .body(new InputStreamResource(data));
    }

    record TokenRequest(String project) {}
}
```

Notes on the data endpoint:
- The `@PreAuthorize` check happened at token exchange time (the `/token` endpoint
  verified the user's OIDC token had the right project role). The data endpoint validates
  the internal token's claims instead.
- `RunAs.runAsSystem()` is used to bypass `@PreAuthorize` on `storageService.loadObject()`
  because the internal token's Principal doesn't carry OIDC roles. This is safe because
  we've already verified: (a) the OIDC token had project access (at exchange time),
  (b) the project claim matches, (c) the IP matches, (d) the token hasn't expired.
- The `{object}` path variable may need to support slashes for nested paths like
  `partitions/partition_0_train.pt`. This can be handled with `@GetMapping("/data/{project}/**")`
  and extracting the remainder from the request path.

---

### Part 4: Docker Network Configuration

**Goal:** Containers on `flower-network` can reach Armadillo's internal port.

Since Armadillo runs directly on the host (not in Docker), containers reach it via the
Docker bridge gateway IP. No `docker-compose.yml` changes are needed for Armadillo
itself — it's not a container.

**How it works:** When Docker creates a bridge network (e.g. `flower-network` with
subnet `172.18.0.0/16`), it assigns the host a gateway IP on that bridge (e.g.
`172.18.0.1`). Containers on the network can reach host services listening on this
gateway IP. Armadillo's internal port (9080) is bound to this IP (configured in Part 1).

**In `DockerService` (feat/flower branch):**

The `createFlowerNetworkIfDoesNotExist()` method already creates the network. After
creating it (or on startup), look up the gateway IP and make it available for
configuration:

```java
private String getFlowerNetworkGateway() {
    List<Network> networks = dockerClient.listNetworksCmd()
        .withNameFilter(flowerNetwork).exec();
    if (!networks.isEmpty()) {
        return networks.get(0).getIpam().getConfig().get(0).getGateway();
    }
    return null;
}
```

**In `DockerService.installSuperExec()` (feat/flower branch):**

When creating the SuperNode container (which runs the SuperExec and spawns ClientApp
subprocesses), set the internal URL using the gateway IP:

```java
String gateway = getFlowerNetworkGateway();
cmd.withEnv("ARMADILLO_INTERNAL_URL=http://" + gateway + ":9080");
```

The container reaches Armadillo at `http://172.18.0.1:9080` — the host's address on
the Docker bridge. No Docker DNS name resolution needed (Armadillo is not a container,
so it has no container hostname on the network).

---

### Part 5: Python Data Access Helpers

**Goal:** Helper functions for Flower client code to exchange tokens and download data.

**New file: `src/molgenis_flwr_armadillo/data.py`**

```python
"""Data access for Flower clients running on Armadillo.

These functions handle the two-step data access flow:
1. Exchange the user's OIDC token for an IP-bound internal token
2. Download data objects using the internal token

Both calls go to Armadillo's internal port (9080), which is only
reachable from within the Docker network.
"""

import io
import os

import requests


def get_internal_token(oidc_token: str, project: str) -> str:
    """Exchange an OIDC token for an IP-bound internal token.

    Args:
        oidc_token: User's OIDC access token (from Flower run_config)
        project: Armadillo project to request access for

    Returns:
        Internal JWT string

    Raises:
        requests.HTTPError: If exchange fails (no project access, invalid token)
    """
    internal_url = os.environ.get("ARMADILLO_INTERNAL_URL")
    if not internal_url:
        raise RuntimeError(
            "ARMADILLO_INTERNAL_URL not set. "
            "This must be set by Armadillo when creating the container.")

    response = requests.post(
        f"{internal_url}/internal/token",
        headers={"Authorization": f"Bearer {oidc_token}"},
        json={"project": project},
    )
    response.raise_for_status()
    return response.json()["token"]


def download_data(token: str, project: str, object_name: str) -> bytes:
    """Download a data object from Armadillo storage.

    Args:
        token: Internal JWT from get_internal_token()
        project: Armadillo project name
        object_name: Path within the project (e.g. "partitions/partition_0_train.pt")

    Returns:
        Raw bytes of the object

    Raises:
        requests.HTTPError: If download fails (expired token, IP mismatch, etc.)
    """
    internal_url = os.environ.get("ARMADILLO_INTERNAL_URL")
    if not internal_url:
        raise RuntimeError(
            "ARMADILLO_INTERNAL_URL not set. "
            "This must be set by Armadillo when creating the container.")

    response = requests.get(
        f"{internal_url}/internal/data/{project}/{object_name}",
        headers={"Authorization": f"Bearer {token}"},
    )
    response.raise_for_status()
    return response.content


def load_tensor(token: str, project: str, object_name: str):
    """Download a .pt file and load as torch tensors.

    Loads directly from bytes in memory — nothing written to disk.

    Args:
        token: Internal JWT from get_internal_token()
        project: Armadillo project name
        object_name: Path within the project

    Returns:
        Whatever torch.load() returns (typically a dict of tensors)
    """
    import torch

    raw = download_data(token, project, object_name)
    return torch.load(io.BytesIO(raw), weights_only=True)
```

**Modify: `src/molgenis_flwr_armadillo/__init__.py`**

```python
from .helpers import extract_tokens, get_node_token
from .data import get_internal_token, download_data, load_tensor
```

---

### Part 6: Update Example App

**Goal:** Update the quickstart-pytorch example to download data from Armadillo.

**Modify: `examples/quickstart-pytorch/pytorchexample/client_app.py`**

```python
from molgenis_flwr_armadillo import get_node_token, get_internal_token, load_tensor

@app.train()
def train(msg: Message, context: Context):
    # Get OIDC token routed through Flower
    oidc_token = get_node_token(msg, context)

    # Exchange for IP-bound internal token
    project = context.run_config.get("armadillo-project", "cifar10")
    internal_token = get_internal_token(oidc_token, project)

    # Download training data (bytes → memory, no disk)
    partition_id = context.node_config["partition-id"]
    train_data = load_tensor(
        internal_token, project,
        f"partitions/partition_{partition_id}_train.pt")
    test_data = load_tensor(
        internal_token, project,
        f"partitions/partition_{partition_id}_test.pt")

    # Build DataLoaders from tensors
    batch_size = context.run_config["batch-size"]
    trainloader, testloader = make_dataloaders(train_data, test_data, batch_size)

    # ... rest of training unchanged ...
```

**Modify: `examples/quickstart-pytorch/pytorchexample/task.py`**

Add a helper to create DataLoaders from downloaded tensor dicts:

```python
from torch.utils.data import DataLoader, TensorDataset

def make_dataloaders(train_data: dict, test_data: dict, batch_size: int):
    """Create DataLoaders from tensor dicts downloaded from Armadillo.

    Args:
        train_data: Dict with "images" and "labels" tensors
        test_data: Dict with "images" and "labels" tensors
        batch_size: Batch size

    Returns:
        (trainloader, testloader)
    """
    train_ds = TensorDataset(train_data["images"], train_data["labels"])
    test_ds = TensorDataset(test_data["images"], test_data["labels"])
    return (
        DataLoader(train_ds, batch_size=batch_size, shuffle=True),
        DataLoader(test_ds, batch_size=batch_size),
    )
```

Update `train()` and `test()` functions to handle tuple batches (TensorDataset returns
`(images, labels)` tuples, not `{"img": ..., "label": ...}` dicts).

**Modify: `examples/quickstart-pytorch/pyproject.toml`**

Add config key for the project name:

```toml
[tool.flwr.app.config]
armadillo-project = "cifar10"
```

---

### Part 7: Data Upload Script

**Goal:** Script to prepare test data and upload to Armadillo for development/testing.

**New file: `scripts/setup_armadillo_data.py`**

This is an admin setup script (not part of the normal user flow):

1. Downloads CIFAR-10 via torchvision
2. Splits into N partitions (deterministic sequential split)
3. For each partition, creates train/test tensor dicts and saves as .pt bytes
4. Creates the project in Armadillo via `POST /storage/projects/{project}`
   (admin basic auth)
5. Uploads each .pt file via `POST /storage/projects/{project}/objects/{path}`

Armadillo object structure after upload:
```
Project: cifar10
  partitions/partition_0_train.pt
  partitions/partition_0_test.pt
  partitions/partition_1_train.pt
  partitions/partition_1_test.pt
```

---

## How the Token Swap Works

This is modelled on Armadillo's existing DataShield resource token swap, adapted for
Flower's architecture.

### DataShield Resource Flow (Existing)

```
User's R client → POST /load-resource (with OIDC token)
    → Armadillo checks @PreAuthorize (ROLE_PROJECT_RESEARCHER)
    → Armadillo generates internal JWT via ResourceTokenService
      (scoped to specific resource, signed with RSA key, 300s TTL)
    → Armadillo injects token into R code executed in the ROCK container
    → R container calls GET /rawfiles with internal token
    → /rawfiles validates issuer + project + object claims
    → Data streams to R container
    → User never sees the internal token
```

### Flower Flow (This Plan)

```
User's laptop → flwr run (OIDC token in run_config)
    → Flower routes to ClientApp subprocess (OIDC token in ConfigRecord)
    → ClientApp calls POST /internal/token (with OIDC token)
    → Armadillo checks @PreAuthorize (ROLE_PROJECT_RESEARCHER)
    → Armadillo generates internal JWT via ResourceTokenService
      (scoped to project, bound to container IP, signed with RSA key, 300s TTL)
    → Returns internal token to ClientApp
    → ClientApp calls GET /internal/data/{project}/{object} (with internal token)
    → Armadillo validates issuer + project + bound_ip claims
    → Data streams to ClientApp
    → User can see the internal token (it's in their code's memory) but:
      - Can't reach port 9080 from outside the Docker network
      - Can't use the token from a different IP
      - Token expires in 300s
```

### How IP-Bound Tokens Work

An IP-bound token is a standard JWT with the requester's IP address stored as a claim.
There is no special cryptographic mechanism — the security comes from two independent,
unforgeable sources being compared:

1. **The `bound_ip` claim** is inside the RSA-signed JWT. It was set when the token was
   created, based on `HttpServletRequest.getRemoteAddr()`. The user can read this value
   but cannot change it without Armadillo's RSA private key (which never leaves the
   Armadillo process).

2. **The request source IP** comes from the TCP/IP stack, not from anything the caller
   sends in headers or body. It is the actual IP address that completed the TCP three-way
   handshake (SYN → SYN-ACK → ACK). To spoof this, the attacker would need to receive
   the SYN-ACK, which is sent to the real IP address — not the attacker.

On each data request, Armadillo compares these two values:

```java
String claimedIp = token.getClaimAsString("bound_ip");   // from signed JWT
String actualIp  = request.getRemoteAddr();               // from TCP connection

if (!claimedIp.equals(actualIp)) {
    // Token was issued to 172.18.0.2 but request came from 172.18.0.1
    throw new ResponseStatusException(HttpStatus.FORBIDDEN);
}
```

Example scenarios:

| Requester | Token's bound_ip | Request source IP | Result |
|-----------|:---:|:---:|:---:|
| Same container (SuperNode) | 172.18.0.2 | 172.18.0.2 | Allowed |
| User SSHed to host | 172.18.0.2 | 172.18.0.1 (gateway) | Rejected (IP mismatch) |
| User on laptop | 172.18.0.2 | can't reach port 9080 | Blocked by network |
| Different container | 172.18.0.2 | 172.18.0.3 | Rejected (IP mismatch) |

---

## Implementation Order

1. **Part 1** — Internal port (can be tested independently with a health-check endpoint)
2. **Part 2** — Port-gating filter (add immediately, before any internal endpoints exist)
3. **Part 3** — Token exchange + data endpoints (the core logic)
4. **Part 4** — Docker network config (needed for integration testing)
5. **Part 7** — Data upload script (creates test data in Armadillo)
6. **Part 5** — Python data helpers (depends on Part 3 endpoints being available)
7. **Part 6** — Example app update (depends on Part 5)

Parts 1–4 are Java (Armadillo). Parts 5–7 are Python (molgenis-flwr-armadillo).

---

## Verification

### Test 1: Network Isolation

```bash
# Find the flower-network gateway IP
GATEWAY=$(docker network inspect flower-network \
  --format '{{range .IPAM.Config}}{{.Gateway}}{{end}}')

# From the host on localhost — should fail (not bound to localhost)
curl http://localhost:9080/internal/token
# Expected: connection refused

# From the host targeting the gateway IP — technically reachable on Linux,
# but the IP-bound token will block actual use (see Test 4)
curl http://$GATEWAY:9080/internal/token
# Expected: 401 (reachable but no auth token)

# From a container on flower-network — should be reachable
docker exec supernode-container \
  curl -s -o /dev/null -w "%{http_code}" http://$GATEWAY:9080/internal/token
# Expected: 401 (reachable, no auth token)
```

### Test 2: Port Gating

```bash
# /internal on public port — should 404
curl http://localhost:8080/internal/token
# Expected: 404

# Normal API on internal port — should 404
docker exec supernode-container \
  curl -s -o /dev/null -w "%{http_code}" http://$GATEWAY:9080/storage/projects
# Expected: 404
```

### Test 3: Token Exchange

```bash
# From within a container, with valid OIDC token for a permitted project
docker exec supernode-container \
  curl -X POST http://$GATEWAY:9080/internal/token \
  -H "Authorization: Bearer <OIDC_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"project": "cifar10"}'
# Expected: {"token": "eyJ..."}

# With OIDC token for a project the user does NOT have access to
# Expected: 403
```

### Test 4: IP Binding

```bash
# From the container that requested the token — should work
docker exec supernode-container curl \
  http://$GATEWAY:9080/internal/data/cifar10/partitions/partition_0_train.pt \
  -H "Authorization: Bearer <INTERNAL_TOKEN>" \
  -o /dev/null -w "%{http_code}"
# Expected: 200

# From a DIFFERENT container — should fail (different source IP)
docker exec other-container curl \
  http://$GATEWAY:9080/internal/data/cifar10/partitions/partition_0_train.pt \
  -H "Authorization: Bearer <INTERNAL_TOKEN>" \
  -o /dev/null -w "%{http_code}"
# Expected: 403 (token bound to 172.18.0.2, request from 172.18.0.3)

# From the host directly (SSH user trying to use a leaked token)
curl http://$GATEWAY:9080/internal/data/cifar10/partitions/partition_0_train.pt \
  -H "Authorization: Bearer <INTERNAL_TOKEN>"
# Expected: 403 (token bound to 172.18.0.2, request from 172.18.0.1)
```

### Test 5: End-to-End Flower Run

```bash
# 1. Upload test data to Armadillo
python scripts/setup_armadillo_data.py --num-partitions 2

# 2. Authenticate
molgenis-flwr-authenticate --config flower-nodes.yaml

# 3. Run
molgenis-flwr-run --app-dir examples/quickstart-pytorch

# Expected:
# - Token exchange logged in Armadillo
# - Data download logged in Armadillo
# - Training completes with decreasing loss
# - Global evaluation reports accuracy
```

---

## Open Questions

1. **Token TTL for multi-round training:** The default 300s TTL may be too short if
   data is re-downloaded each round. Options: (a) download data once at the start of
   training and hold in memory for all rounds, (b) increase TTL via config, (c) re-exchange
   on each round (the OIDC token typically lives longer). Option (a) is simplest and
   matches the current example app structure.

2. **Nested object paths:** The `{object}` path variable in `/internal/data/{project}/{object}`
   needs to support slashes (e.g. `partitions/partition_0_train.pt`). Use
   `@GetMapping("/data/{project}/**")` and extract the object path from the request URI.

3. **Server-side evaluation:** The ServerApp needs test data for `global_evaluate()`.
   The ServerApp runs in a SuperExec connected to the SuperLink, not on the Armadillo
   node. Options: (a) skip server-side global evaluation and use client-side evaluation
   only, (b) route a token to the ServerApp as well (same mechanism, but the ServerApp
   container needs to be on a network that can reach Armadillo's internal port).

4. **OIDC token expiry:** If the OIDC access token expires during a long training run
   and the client needs to re-exchange, it won't work. The `authenticate.py` already
   requests `offline_access` scope, so a refresh token is available. A future enhancement
   could add token refresh to the Python helpers.

5. **Branch merging:** The Docker container management code on `feat/flower` needs to be
   merged into `epic/flower` before starting implementation. The `installSuperExec()`
   method is where `ARMADILLO_INTERNAL_URL` gets injected.

6. **Bridge gateway IP stability:** The Docker bridge gateway IP (e.g. `172.18.0.1`) is
   assigned when the network is created and stays stable while the network exists. If the
   network is deleted and recreated, the IP may change. The `internal-bind-address` config
   would need updating. This could be automated: `DockerService` looks up the gateway IP
   at startup and writes it to config, or the `InternalPortConfig` queries Docker for it
   directly.

7. **Armadillo-as-container deployment:** Some deployments may run Armadillo in Docker
   (e.g. the quickstart docker-compose). In that case, Armadillo would be a container on
   `flower-network` with its own IP, and the internal port could be bound to `0.0.0.0`
   within the container (since the container's network namespace is isolated). Port 9080
   would simply not be published (`-p` only maps 8080). The `InternalPortConfig` should
   handle both cases: if `internal-bind-address` is set, bind to it (host deployment);
   if empty but internal port is configured, bind to `0.0.0.0` (container deployment).
