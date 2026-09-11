"""Wrapper around ``flwr run`` that injects Armadillo auth tokens.

Usage:
    armadillo-flwr-run [flwr run arguments...]

Loads tokens saved by ``armadillo-flwr-authenticate``, bundles them under the
single ``armadillo-tokens`` run-config key and hands them to ``flwr run`` via
a private TOML file rather than argv, so they never appear in process listings.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from rich.console import Console

from molgenis_flwr_armadillo.authenticate import load_tokens
from molgenis_flwr_armadillo.helpers import TOKENS_KEY

console = Console()


def build_command(args: list[str], config_path: Path) -> list[str]:
    """Build the flwr run command pointing --run-config at the token file."""
    return ["flwr", "run", *args, "--run-config", str(config_path)]


def write_run_config(tokens: dict) -> Path:
    """Write the token bundle to a private (0600) TOML file and return its path."""
    blob = base64.b64encode(json.dumps(tokens).encode()).decode()
    fd, path = tempfile.mkstemp(suffix=".toml")
    with os.fdopen(fd, "w") as f:
        f.write(f'{TOKENS_KEY} = "{blob}"\n')
    return Path(path)


def main() -> None:
    try:
        tokens = load_tokens()
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        sys.exit(1)

    console.print("[dim]Injecting tokens from armadillo-flwr-authenticate[/dim]")
    config_path = write_run_config(tokens)
    try:
        result = subprocess.run(build_command(sys.argv[1:], config_path), check=False)
    finally:
        config_path.unlink(missing_ok=True)
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
