"""Helper functions for Flower apps running with Armadillo."""

import os
import re

from flwr.app import Context, Message

ARMADILLO_URL = os.environ.get("ARMADILLO_URL", "")


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
    """Extract all tokens from run_config for passing to clients.

    Use in server_app.py to collect tokens for the train_config.

    Args:
        context: The Flower Context object

    Returns:
        Dict of token keys to values,
        e.g. {"token-armadillo-demo-molgenis-net": "eyJ..."}

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
        if k.startswith("token-")
    }


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
    token = msg.content.get("config", {}).get(f"token-{key}", "")
    if not token:
        raise RuntimeError(
            f"No token found for URL '{url}' (key: token-{key}). "
            f"Re-run armadillo-flwr-authenticate if tokens have expired."
        )
    return token