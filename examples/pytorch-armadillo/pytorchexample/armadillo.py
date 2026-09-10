"""Vendored Armadillo helpers (from molgenis-flwr-armadillo).

Flower Hub builds the FAB server-side, so dependencies must be
pip-resolvable; molgenis-flwr-armadillo is not on PyPI yet. This module
vendors the helpers the app needs. Keep in sync with
molgenis-flwr-armadillo src/molgenis_flwr_armadillo/helpers.py.
"""

import base64
import json
import os
import re
import time
from pathlib import Path

import requests
from flwr.app import Context, Message

DATA_DIR = Path("/tmp/armadillo_data")
CONTAINER_NAME = os.environ.get("ARMADILLO_CONTAINER_NAME", "")
ARMADILLO_URL = os.environ.get("ARMADILLO_URL", "")

# All node tokens travel in one declared run-config key as base64(JSON
# {sanitized-url: token}); a published Hub app can't declare per-node keys.
TOKENS_KEY = "armadillo-tokens"


def sanitize_url(url: str) -> str:
    """Convert a URL into a safe key for use in Flower run config.

    Strips the scheme and trailing slashes, lowercases, and replaces
    non-alphanumeric characters with hyphens.
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
    """Return the armadillo-tokens bundle from run_config for forwarding."""
    blob = context.run_config.get(TOKENS_KEY, "")
    return {TOKENS_KEY: blob} if blob else {}


def get_node_url() -> str:
    """Get this node's Armadillo URL from the ARMADILLO_URL environment variable.

    The URL is injected by Armadillo when starting the container.
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


def _auth_headers(token: str) -> dict:
    """Build authorization headers."""
    return {"Authorization": f"Bearer {token}"}


def _request(method: str, url: str, token: str, path: str, **kwargs):
    """Make an authenticated request to Armadillo with error handling."""
    endpoint = f"{url.rstrip('/')}{path}"
    try:
        response = requests.request(
            method, endpoint, headers=_auth_headers(token), **kwargs
        )
        response.raise_for_status()
        return response
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else "unknown"
        if status == 401:
            raise RuntimeError(
                f"Authentication failed (HTTP 401) from {endpoint}. "
                f"The OIDC token may have expired. "
                f"Re-run armadillo-flwr-authenticate to get a new token."
            ) from e
        elif status == 403:
            raise RuntimeError(
                f"Access denied (HTTP 403) from {endpoint}. "
                f"The authenticated user does not have permission to access "
                f"this resource. Check project permissions in Armadillo."
            ) from e
        elif status == 404:
            raise RuntimeError(
                f"Not found (HTTP 404) from {endpoint}. "
                f"The project or resource may not exist."
            ) from e
        else:
            raise RuntimeError(f"HTTP {status} from {endpoint}: {e}") from e
    except requests.exceptions.ConnectionError as e:
        raise RuntimeError(
            f"Could not connect to Armadillo at {endpoint}. "
            f"Check that the server is running and the URL is correct."
        ) from e


def load_data(url: str, token: str, project: str, resource: str) -> bytes:
    """Request data from Armadillo, load into memory, delete file.

    Calls POST /flower/push-data on Armadillo, which copies the data
    into this container at /tmp/armadillo_data/. The file is read into
    memory and deleted immediately.
    """
    if not CONTAINER_NAME:
        raise RuntimeError("ARMADILLO_CONTAINER_NAME environment variable not set")

    _request(
        "POST", url, token, "/flower/push-data",
        json={
            "project": project,
            "resource": resource,
            "containerName": CONTAINER_NAME,
        },
    )

    filename = project + "_" + resource.replace("/", "_")
    filepath = DATA_DIR / filename

    timeout = 300
    start = time.monotonic()
    while not filepath.exists():
        if time.monotonic() - start > timeout:
            raise TimeoutError(f"Data file {filepath} did not arrive within {timeout}s")
        time.sleep(0.1)

    raw_bytes = filepath.read_bytes()
    filepath.unlink()
    return raw_bytes
