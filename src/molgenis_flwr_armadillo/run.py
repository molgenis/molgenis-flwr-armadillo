"""Submit a pre-signed FAB to a Flower SuperLink via gRPC.

Usage:
    molgenis-flwr-run --signed-fab <study.sfab> --federation-address <host:port>

The researcher receives a .sfab file from the data steward (who signed it)
and submits it without ever having the private key.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys

import grpc
from flwr.common.config import parse_config_args
from flwr.common.serde import fab_to_proto, user_config_to_proto
from flwr.common.typing import Fab
from flwr.proto.control_pb2 import StartRunRequest, StreamLogsRequest
from flwr.proto.control_pb2_grpc import ControlStub
from rich.console import Console

console = Console()


def submit_signed_fab(
    sfab_path: str,
    federation_address: str,
    config_overrides: list[str] | None = None,
    stream: bool = False,
) -> int:
    """Load pre-signed FAB and submit to SuperLink via gRPC.

    Returns the run_id assigned by the SuperLink.
    If stream=True, streams logs to stdout until the run finishes.
    """
    with open(sfab_path) as f:
        sfab = json.load(f)

    fab_bytes = base64.b64decode(sfab["fab_content"])
    fab = Fab(sfab["fab_hash"], fab_bytes, sfab["verifications"])

    override_config = parse_config_args(config_overrides) if config_overrides else {}

    channel = grpc.insecure_channel(federation_address)
    stub = ControlStub(channel)

    req = StartRunRequest(
        fab=fab_to_proto(fab),
        override_config=user_config_to_proto(override_config),
    )
    res = stub.StartRun(req)
    run_id = res.run_id

    if stream and run_id:
        console.print(f"[green]Run started with ID: {run_id}[/green]")
        console.print("Streaming logs...")
        try:
            log_stream = stub.StreamLogs(StreamLogsRequest(run_id=run_id))
            for response in log_stream:
                if response.log_output:
                    print(response.log_output, end="", flush=True)
        except grpc.RpcError as e:
            if e.code() != grpc.StatusCode.CANCELLED:
                console.print(f"[red]Log stream error: {e.code().name}[/red]")
        except KeyboardInterrupt:
            console.print("\n[yellow]Stream interrupted.[/yellow]")

    channel.close()
    return run_id


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Submit a pre-signed FAB to a Flower SuperLink"
    )
    parser.add_argument(
        "--signed-fab", required=True, help="Path to .sfab file"
    )
    parser.add_argument(
        "--federation-address",
        required=True,
        help="SuperLink gRPC address (host:port)",
    )
    parser.add_argument(
        "--run-config",
        nargs="*",
        help="Config overrides (e.g. 'key1=\"val1\" key2=123')",
    )
    parser.add_argument(
        "--stream",
        action="store_true",
        help="Stream run logs to stdout until the run finishes",
    )
    args = parser.parse_args()

    console.print(f"Submitting signed FAB: [cyan]{args.signed_fab}[/cyan]")
    console.print(f"Federation address:    [cyan]{args.federation_address}[/cyan]")

    try:
        run_id = submit_signed_fab(
            args.signed_fab, args.federation_address, args.run_config,
            stream=args.stream,
        )
    except grpc.RpcError as e:
        console.print(f"[red]gRPC error: {e.code().name} — {e.details()}[/red]")
        sys.exit(1)

    if not args.stream:
        console.print(f"[green]Run started with ID: {run_id}[/green]")


if __name__ == "__main__":
    main()
