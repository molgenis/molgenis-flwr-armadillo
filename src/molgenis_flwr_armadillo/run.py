"""Run Flower on Armadillo with saved tokens."""

import argparse
import subprocess
import sys

from rich.console import Console
from molgenis_flwr_armadillo.authenticate import load_tokens

console = Console()


def run(app_dir: str = ".", extra_args: list = None) -> None:
    """
    Run Flower with saved tokens.

    Args:
        app_dir: Path to Flower app directory
        extra_args: Additional arguments to pass to flwr run
    """
    extra_args = extra_args or []

    try:
        tokens = load_tokens()
    except FileNotFoundError as e:
        console.print(f"[red]✗ {e}[/red]")
        sys.exit(1)

    # Build run-config string
    config_parts = [f'{key}="{value}"' for key, value in tokens.items()]
    run_config = " ".join(config_parts)

    # Build command: flwr run <app-dir> --run-config <tokens> [extra args...]
    cmd = ["flwr", "run", app_dir, "--run-config", run_config] + extra_args

    console.print("[bold]Molgenis Flower Armadillo[/bold]")
    console.print()
    console.print(f"Running: [cyan]flwr run {app_dir}[/cyan]")
    console.print(f"With tokens for: [green]{', '.join(t.replace('token-', '') for t in tokens.keys())}[/green]")
    if extra_args:
        console.print(f"Extra args: [yellow]{' '.join(extra_args)}[/yellow]")
    console.print(f"[dim]run-config: {run_config[:100]}...[/dim]")
    console.print()

    result = subprocess.run(cmd)
    sys.exit(result.returncode)


def main():
    """CLI entry point.

    Usage:
        molgenis-flwr-run --app-dir <path> [-- <flwr-run-args>]

    Examples:
        # Basic run
        molgenis-flwr-run --app-dir examples/quickstart-pytorch

        # With log streaming
        molgenis-flwr-run --app-dir examples/quickstart-pytorch -- --stream

        # With federation and streaming
        molgenis-flwr-run --app-dir examples/quickstart-pytorch -- --stream --federation local-deployment
    """
    parser = argparse.ArgumentParser(
        description="Run Flower with saved tokens",
        epilog="Any arguments after -- are passed directly to 'flwr run'"
    )
    parser.add_argument(
        "--app-dir",
        default=".",
        help="Path to Flower app directory"
    )

    # Parse known args, everything else goes to flwr run
    args, extra_args = parser.parse_known_args()

    # Remove leading '--' if present (used to separate our args from flwr args)
    if extra_args and extra_args[0] == "--":
        extra_args = extra_args[1:]

    run(args.app_dir, extra_args)


if __name__ == "__main__":
    main()
