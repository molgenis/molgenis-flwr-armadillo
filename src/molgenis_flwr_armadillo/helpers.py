"""Helper functions for Flower apps running with Armadillo."""

import os
import re
import time
from pathlib import Path

import requests
from flwr.app import Context, Message

DATA_DIR = Path("/tmp/armadillo_data")
CONTAINER_NAME = os.environ.get("ARMADILLO_CONTAINER_NAME", "")
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


def list_projects(url: str, token: str) -> list[str]:
    """List projects the authenticated user has access to.

    Calls GET /my/projects on Armadillo.

    Args:
        url: Armadillo server URL
        token: OIDC Bearer token

    Returns:
        List of project names the user can access

    Example:
        from molgenis_flwr_armadillo import list_projects

        projects = list_projects("http://localhost:8080", token)
        print(projects)  # ["project-a", "project-b"]
    """
    response = _request("GET", url, token, "/my/projects")
    return response.json()


def list_resources(url: str, token: str, project: str) -> list[str]:
    """List resources (objects) in a project the user has access to.

    Calls GET /storage/projects/{project}/objects on Armadillo.
    Equivalent to datashield.tables() for Flower projects.

    Args:
        url: Armadillo server URL
        token: OIDC Bearer token
        project: Armadillo project name

    Returns:
        List of resource paths in the project

    Raises:
        RuntimeError: If the user does not have access or the project
            does not exist

    Example:
        from molgenis_flwr_armadillo import list_resources

        resources = list_resources("http://localhost:8080", token, "my-project")
        print(resources)  # ["data/train.pt", "data/test.pt"]
    """
    response = _request("GET", url, token, f"/storage/projects/{project}/objects")
    return response.json()


def check_access(url: str, token: str, project: str, resources: list[str] = None):
    """Verify the user has access to a project and its resources.

    Checks that the project is accessible and optionally that specific
    resources exist. Raises RuntimeError with a clear message on failure.

    Args:
        url: Armadillo server URL
        token: OIDC Bearer token
        project: Armadillo project name
        resources: Optional list of resource paths to verify exist

    Raises:
        RuntimeError: If the user cannot access the project or resources
            are missing

    Example:
        from molgenis_flwr_armadillo import check_access

        # Verify access before starting training
        check_access(url, token, "my-project", ["data/train.pt", "data/test.pt"])
    """
    projects = list_projects(url, token)
    if project not in projects:
        raise RuntimeError(
            f"User does not have access to project '{project}' on {url}. "
            f"Available projects: {projects}. "
            f"Grant access in Armadillo via POST /access/permissions."
        )

    if resources:
        available = list_resources(url, token, project)
        missing = [r for r in resources if r not in available]
        if missing:
            raise RuntimeError(
                f"Resources not found in project '{project}' on {url}: {missing}. "
                f"Available resources: {available}"
            )


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
            url = get_node_url()
            token = get_node_token(msg)
            raw = load_data(url, token, "myproject", "train.parquet")
            df = pd.read_parquet(io.BytesIO(raw))
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