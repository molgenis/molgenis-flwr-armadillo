# molgenis-flwr-armadillo

A wrapper for running [Flower](https://flower.ai/) federated learning with [MOLGENIS Armadillo](https://github.com/molgenis/molgenis-service-armadillo).

The open-source edition of Flower doesn't include individual-level authentication. This package extends Flower by providing CLI tools to authenticate with Armadillo servers and run Flower jobs with tokens automatically injected.

## Installation

```bash
pip install molgenis-flwr-armadillo
```

Or from source:

```bash
pip install git+https://github.com/molgenis/molgenis-flwr-armadillo.git
```

## Quick Start

```bash
# 1. Authenticate to all Armadillo servers (opens browser for each)
armadillo-flwr-authenticate --config flower-nodes.yaml

# 2. Run the Flower app with tokens automatically injected
armadillo-flwr-run .
```

## CLI Tools

| Command | Description |
|---------|-------------|
| `armadillo-flwr-authenticate` | Authenticate to Armadillo servers via OIDC |
| `armadillo-flwr-run` | Run a Flower app with tokens injected |
| `armadillo-flwr-resources` | List accessible projects and resources |
