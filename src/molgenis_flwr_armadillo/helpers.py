"""Helper functions for Flower apps running with Armadillo."""

import base64
import json
import os
import re

from flwr.app import Context, Message

ARMADILLO_URL = os.environ.get("ARMADILLO_URL", "")

# One declared run-config key carries every node token as base64(JSON
# {sanitized-url: token}): a published Flower Hub app must declare each
# run-config key up front, and per-node keys are only known at run time.
TOKENS_KEY = "armadillo-tokens"


def sanitize_url(url: str) -> str:
    """Convert a URL into a safe key for use in Flower run config.

    Strips the scheme and trailing slashes, lowercases, and replaces
    non-alphanumeric characters with hyphens.

    Args:
        url: An Armadillo server URL

    Returns:
        A sanitized string safe for use as a config key,
        e.g. "https://armadillo-demo.molgenis.net/" -> "armadillo-demo-molgenis-net"

    Raises:
        ValueError: If the URL is empty or sanitizes to an empty string
    """
    if not url:
        raise ValueError("URL must not be empty")
    key = url.lower()
    key = re.sub(r"^https?://", "", key)
    key = key.strip("/")
    key = re.sub(r"[^a-z0-9]+", "-", key)
    key = key.strip("-")
    if not key:
        raise ValueError(f"URL sanitizes to empty string: {url}")
    return key


def extract_tokens(context: Context) -> dict:
    """Extract the token bundle from run_config for passing to clients.

    Returns the single ``armadillo-tokens`` run-config entry (a base64-encoded
    JSON map of {sanitized-url: token}) so the ServerApp can forward it to
    clients in the train/eval config. Empty dict if no tokens were provided.

    Use in server_app.py to collect tokens for the train_config.

    Args:
        context: The Flower Context object

    Returns:
        {"armadillo-tokens": "<base64>"} if present, else {}

    Example:
        from molgenis_flwr_armadillo import extract_tokens

        @app.main()
        def main(grid: Grid, context: Context) -> None:
            lr = context.run_config["learning-rate"]
            tokens = extract_tokens(context)
            train_config = ConfigRecord({"lr": lr, **tokens})
            # ...
    """
    blob = context.run_config.get(TOKENS_KEY, "")
    return {TOKENS_KEY: blob} if blob else {}


def get_node_url() -> str:
    """Get this node's Armadillo URL from the ARMADILLO_URL environment variable.

    The URL is injected by Armadillo when starting the container.

    Returns:
        The Armadillo URL for this node

    Raises:
        RuntimeError: If ARMADILLO_URL is not set

    Example:
        from molgenis_flwr_armadillo import get_node_url

        @app.train()
        def train(msg: Message, context: Context):
            url = get_node_url()
    """
    if not ARMADILLO_URL:
        raise RuntimeError(
            "ARMADILLO_URL environment variable not set. "
            "Check that the container was started by Armadillo."
        )
    return ARMADILLO_URL


def get_node_token(msg: Message) -> str:
    """Extract this node's token from the message config.

    Uses the ARMADILLO_URL environment variable to find the matching token.

    Args:
        msg: The Flower Message received from the server

    Returns:
        The token string for this node

    Raises:
        RuntimeError: If ARMADILLO_URL is not set or token is missing

    Example:
        from molgenis_flwr_armadillo import get_node_token

        @app.train()
        def train(msg: Message, context: Context):
            token = get_node_token(msg)
            data = fetch_from_armadillo(token)
            # ...
    """
    url = get_node_url()
    key = sanitize_url(url)
    blob = msg.content.get("config", {}).get(TOKENS_KEY, "")
    if not blob:
        raise RuntimeError(
            f"No '{TOKENS_KEY}' found in message config. "
            f"Was the run submitted with armadillo-flwr-run?"
        )
    try:
        tokens = json.loads(base64.b64decode(blob).decode())
    except (ValueError, json.JSONDecodeError) as e:
        raise RuntimeError(f"Failed to decode '{TOKENS_KEY}': {e}") from e
    token = tokens.get(key, "")
    if not token:
        raise RuntimeError(
            f"No token found for URL '{url}' (key: {key}). "
            f"Available keys: {list(tokens)}. "
            f"Re-run armadillo-flwr-authenticate if tokens have expired."
        )
    return token