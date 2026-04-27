"""Wrapper around ``flwr run`` that injects Armadillo auth tokens.

Usage:
    armadillo-flwr-run [flwr run arguments...]

Loads tokens saved by ``armadillo-flwr-authenticate`` and passes them
as --run-config overrides to ``flwr run``.
"""

from __future__ import annotations

import subprocess
import sys

from rich.console import Console

from molgenis_flwr_armadillo.authenticate import load_tokens

console = Console()


def build_command(args: list[str]) -> list[str]:
    """Build the flwr run command with token overrides."""
    tokens = load_tokens()
    token_config = " ".join(
        f'{k}="{v}"' for k, v in tokens.items() if k.startswith("token-")
    )
    return ["flwr", "run", *args, "--run-config", token_config]


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
