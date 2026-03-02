"""Helper functions for Flower apps running with Armadillo."""

import os
import time
from pathlib import Path

import requests
from flwr.app import Context, Message

DATA_DIR = Path("/tmp/armadillo_data")
CONTAINER_NAME = os.environ.get("ARMADILLO_CONTAINER_NAME", "")


def extract_tokens(context: Context) -> dict:
    """Extract all tokens and URLs from run_config for passing to clients.

    Use in server_app.py to collect tokens and URLs for the train_config.

    Args:
        context: The Flower Context object

    Returns:
        Dict of token/url keys to values,
        e.g. {"token-demo": "eyJ...", "url-demo": "https://..."}

    Example:
        from molgenis_flwr_armadillo import extract_tokens

        @app.main()
        def main(grid: Grid, context: Context) -> None:
            lr = context.run_config["learning-rate"]
            tokens = extract_tokens(context)
            train_config = ConfigRecord({"lr": lr, **tokens})
            # ...
    """
    return {
        k: v
        for k, v in context.run_config.items()
        if k.startswith("token-") or k.startswith("url-")
    }


def get_node_token(msg: Message, context: Context) -> str:
    """Extract this node's token from the message config.

    Use in client_app.py to get the token for this specific node.

    Args:
        msg: The Flower Message received from the server
        context: The Flower Context object

    Returns:
        The token string for this node, or empty string if not found

    Example:
        from molgenis_flwr_armadillo import get_node_token

        @app.train()
        def train(msg: Message, context: Context):
            token = get_node_token(msg, context)
            data = fetch_from_armadillo(token)
            # ...
    """
    node_name = context.node_config.get("node-name", "")
    return msg.content.get("config", {}).get(f"token-{node_name}", "")


def get_node_url(msg: Message, context: Context) -> str:
    """Extract this node's Armadillo URL from the message config.

    Use in client_app.py to get the Armadillo server URL for this node.

    Args:
        msg: The Flower Message received from the server
        context: The Flower Context object

    Returns:
        The Armadillo URL for this node, or empty string if not found

    Example:
        from molgenis_flwr_armadillo import get_node_url

        @app.train()
        def train(msg: Message, context: Context):
            url = get_node_url(msg, context)
    """
    node_name = context.node_config.get("node-name", "")
    return msg.content.get("config", {}).get(f"url-{node_name}", "")


def load_data(url: str, token: str, project: str, resource: str) -> bytes:
    """Request data from Armadillo, load into memory, delete file.

    Calls POST /flower/push-data on Armadillo, which copies the data
    into this container at /tmp/armadillo_data/. The file is read into
    memory and deleted immediately.

    Args:
        url: Armadillo server URL (from get_node_url)
        token: OIDC Bearer token (from get_node_token)
        project: Armadillo project name
        resource: Resource path within the project

    Returns:
        Raw bytes of the resource file

    Example:
        from molgenis_flwr_armadillo import get_node_token, get_node_url, load_data

        @app.train()
        def train(msg: Message, context: Context):
            url = get_node_url(msg, context)
            token = get_node_token(msg, context)
            raw = load_data(url, token, "myproject", "train.parquet")
            df = pd.read_parquet(io.BytesIO(raw))
    """
    if not CONTAINER_NAME:
        raise RuntimeError("ARMADILLO_CONTAINER_NAME environment variable not set")

    response = requests.post(
        f"{url.rstrip('/')}/flower/push-data",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "project": project,
            "resource": resource,
            "containerName": CONTAINER_NAME,
        },
    )
    response.raise_for_status()

    filename = project + "_" + resource.replace("/", "_")
    filepath = DATA_DIR / filename

    timeout = 30
    start = time.monotonic()
    while not filepath.exists():
        if time.monotonic() - start > timeout:
            raise TimeoutError(f"Data file {filepath} did not arrive within {timeout}s")
        time.sleep(0.1)

    raw_bytes = filepath.read_bytes()
    filepath.unlink()
    return raw_bytes