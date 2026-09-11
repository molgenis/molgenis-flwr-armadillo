"""Load Armadillo data into the Flower client container."""

import os
from pathlib import Path

from molgenis_flwr_armadillo._http import _request

DATA_DIR = Path("/tmp/armadillo_data")
CONTAINER_NAME = os.environ.get("ARMADILLO_CONTAINER_NAME", "")


def load_data(url: str, token: str, project: str, resource: str) -> bytes:
    """Request data from Armadillo, load into memory, delete file.

    Calls POST /flower/push-data on Armadillo, which copies the data
    into this container at /tmp/armadillo_data/ before responding. The
    file is read into memory and deleted immediately.

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
        timeout=300,
        json={
            "project": project,
            "resource": resource,
            "containerName": CONTAINER_NAME,
        },
    )

    # Must match the filename Armadillo writes (FlowerDataService: project + "_" + resource with "/" -> "%2F").
    filepath = DATA_DIR / (project + "_" + resource.replace("/", "%2F"))
    if not filepath.exists():
        raise RuntimeError(
            f"Armadillo accepted the push but {filepath} was not written to this container"
        )

    raw_bytes = filepath.read_bytes()
    filepath.unlink()
    return raw_bytes
