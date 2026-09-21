# Token Routing

## Overview

Flower's open-source edition has no built-in authentication. This package adds OIDC token routing so each client node can authenticate with its local Armadillo server.

## How It Works

```
Researcher                 Flower                   Container
    |                         |                         |
    | authenticate            |                         |
    | (OIDC per URL)          |                         |
    |                         |                         |
    | armadillo-flwr-run      |                         |
    | (inject tokens) ------->|                         |
    |                         |                         |
    |                    ServerApp                      |
    |                    extract_tokens()               |
    |                    forward via ConfigRecord        |
    |                         |                         |
    |                         |------------------------>|
    |                         |                  get_node_url()
    |                         |                  (reads ARMADILLO_URL env)
    |                         |                  get_node_token(msg)
    |                         |                  (matches by sanitized URL)
    |                         |                         |
```

## URL Sanitization

Each Armadillo URL is converted to a config-safe key using `sanitize_url()`:

| URL | Sanitized Key |
|-----|---------------|
| `https://armadillo-demo.molgenis.net` | `armadillo-demo-molgenis-net` |
| `http://localhost:8080` | `localhost-8080` |
| `https://armadillo.dev.molgenis.org/` | `armadillo-dev-molgenis-org` |

The sanitization:

1. Lowercases the URL
2. Strips the scheme (`https://`)
3. Strips trailing slashes
4. Replaces non-alphanumeric characters with hyphens
5. Collapses consecutive hyphens

This ensures `https://Demo.Molgenis.NET/` and `http://demo.molgenis.net` produce the same key.

## Token File Format

After authentication, tokens are saved as:

```json
{
  "token-armadillo-demo-molgenis-net": "eyJ...",
  "url-armadillo-demo-molgenis-net": "https://armadillo-demo.molgenis.net"
}
```

The `token-*` keys are injected into Flower's `--run-config`. The `url-*` keys are kept locally for the `armadillo-flwr-resources` CLI.

## Environment Variable

Armadillo injects the `ARMADILLO_URL` environment variable into each container it starts. The helper functions read this to identify which token belongs to the current node — no manual configuration needed on the container side.
