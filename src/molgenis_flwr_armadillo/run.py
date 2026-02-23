"""Run Flower on Armadillo with saved tokens."""

import argparse
import subprocess
import sys

from rich.console import Console
from molgenis_flwr_armadillo.authenticate import load_tokens

console = Console()

def run(app_dir: str = ".") -> None:
    """
    Run Flower with saved tokens.

    Args:
        app_dir: Path to Flower app directory
    """
    try:
        tokens = load_tokens()
    except FileNotFoundError as e:
        console.print(f"[red]✗ {e}[/red]")
        sys.exit(1)

    # Build run-config string
    config_parts = [f'{key}="{value}"' for key, value in tokens.items()]
    run_config = " ".join(config_parts)

    # Build command
    cmd = ["flwr", "run", app_dir, "--run-config", run_config]

    console.print("[bold]Molgenis Flower Armadillo[/bold]")
    console.print()
    console.print(f"Running: [cyan]flwr run {app_dir}[/cyan]")
    console.print(f"With tokens for: [green]{', '.join(t.replace('token-', '') for t in tokens.keys())}[/green]")
    console.print(f"[dim]run-config: {run_config[:100]}...[/dim]")
    console.print(f"[dim]Full command: {' '.join(cmd[:4])} --run-config '...'[/dim]")
    console.print()

    result = subprocess.run(cmd)
    sys.exit(result.returncode)

def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Run Flower with saved tokens")
    parser.add_argument(
        "--app-dir",
        default=".",
        help="Path to Flower app directory"
    )
    args = parser.parse_args()
    run(args.app_dir)

if __name__ == "__main__":
    main()
