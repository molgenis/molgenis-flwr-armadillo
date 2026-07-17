"""Wrapper around ``flwr run`` that injects Armadillo auth tokens.

Usage:
    armadillo-flwr-run [flwr run arguments...]

Loads tokens saved by ``armadillo-flwr-authenticate`` and passes them
as --run-config overrides to ``flwr run``.
"""

from __future__ import annotations

import base64
import json
import subprocess
import sys

from rich.console import Console

from molgenis_flwr_armadillo.authenticate import load_tokens
from molgenis_flwr_armadillo.helpers import TOKENS_KEY

console = Console()


def build_command(args: list[str]) -> list[str]:
    """Build the flwr run command with a single token-bundle override.

    All node tokens are bundled into one base64-encoded JSON map of
    {sanitized-url: token} under the ``armadillo-tokens`` run-config key. A
    published Flower Hub app declares only that one key, so per-node token
    keys (unknown until run time) never need declaring.
    """
    tokens = load_tokens()
    mapping = {
        k[len("token-"):]: v
        for k, v in tokens.items()
        if k.startswith("token-")
    }
    blob = base64.b64encode(json.dumps(mapping).encode()).decode()
    return ["flwr", "run", *args, "--run-config", f"{TOKENS_KEY}='{blob}'"]


def main() -> None:
    args = sys.argv[1:]

    try:
        cmd = build_command(args)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        sys.exit(1)

    console.print("[dim]Injecting tokens from armadillo-flwr-authenticate[/dim]")
    result = subprocess.run(cmd)
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
