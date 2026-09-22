"""Load Armadillo data into the Flower client container."""

import os
from pathlib import Path

from flwr.app import Message

from molgenis_flwr_armadillo._http import _request
from molgenis_flwr_armadillo.helpers import get_node_token, get_node_url

DATA_DIR = Path("/tmp/armadillo_data")
CONTAINER_NAME = os.environ.get("ARMADILLO_CONTAINER_NAME", "")


def load_data(msg: Message, project: str, resource: str) -> bytes:
    """Request data from Armadillo, load into memory, delete file.

    Calls POST /flower/push-data on this node's Armadillo, which copies
    the data into this container at /tmp/armadillo_data/ before
    responding. The file is read into memory and deleted immediately.

    Args:
        msg: The Flower Message received from the server
        project: Armadillo project name
        resource: Resource path within the project

    Returns:
        Raw bytes of the resource file

    Example:
        from molgenis_flwr_armadillo import load_data

        @app.train()
        def train(msg: Message, context: Context):
            raw = load_data(msg, "myproject", "train.parquet")
            df = pd.read_parquet(io.BytesIO(raw))
    """
    if not CONTAINER_NAME:
        raise RuntimeError("ARMADILLO_CONTAINER_NAME environment variable not set")

    _request(
        "POST", get_node_url(), get_node_token(msg), "/flower/push-data",
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
