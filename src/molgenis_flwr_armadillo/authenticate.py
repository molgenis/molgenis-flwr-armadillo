"""Token management for Flower federated learning with Armadillo."""

import argparse
import json
import os
import tempfile
from pathlib import Path

import requests
import yaml
from molgenis_auth import MolgenisAuthClient
from rich.console import Console
from rich.table import Table

from molgenis_flwr_armadillo.helpers import sanitize_url

console = Console()

TOKEN_FILE = Path(tempfile.gettempdir()) / "flwr_tokens.json"


def get_auth_info(armadillo_url: str) -> dict:
    """Get auth info from Armadillo server.

    Args:
        armadillo_url: Base URL of Armadillo server

    Returns:
        Dict with 'clientId' and 'issuerUri'
    """
    info_url = f"{armadillo_url.rstrip('/')}/actuator/info"
    response = requests.get(info_url, timeout=30)
    response.raise_for_status()
    return response.json()["auth"]


def load_node_urls(config_path: str) -> list[str]:
    """Read the Armadillo URLs from a flower-nodes.yaml config."""
    with open(config_path) as f:
        return yaml.safe_load(f)["urls"]


def authenticate_node(url: str) -> str:
    """Run the OIDC device flow against one Armadillo and return its access token."""
    console.print(f"[bold blue]{url}[/bold blue]")
    with console.status("Fetching auth info..."):
        auth_info = get_auth_info(url)

    client = MolgenisAuthClient(
        auth_server=auth_info["issuerUri"],
        client_id=auth_info["clientId"],
        scopes="openid offline_access",
    )
    return client.device_flow_auth()["access_token"]


def print_summary(urls: list[str]) -> None:
    """Print the table of authenticated nodes."""
    console.print()
    table = Table(title="Authenticated node" if len(urls) == 1 else "Authenticated nodes")
    table.add_column("URL", style="cyan")
    table.add_column("Status", style="green")
    for url in urls:
        table.add_row(url, "✓ Ready")
    console.print(table)


def authenticate(config_path: str) -> dict:
    """Authenticate to every node in the config and save the tokens.

    Args:
        config_path: Path to YAML config file with list of Armadillo URLs

    Returns:
        Dictionary of {sanitized-url: access token}
    """
    urls = load_node_urls(config_path)
    noun = "node" if len(urls) == 1 else "nodes"
    console.print(f"[bold]Authenticating to {len(urls)} Armadillo {noun} from {config_path}[/bold]\n")
    tokens = {sanitize_url(url): authenticate_node(url) for url in urls}
    save_tokens(tokens)
    print_summary(urls)
    return tokens


def save_tokens(tokens: dict) -> None:
    """Save tokens to a private (0600) temp file."""
    fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(tokens, f)
    # os.open's 0o600 only applies when it creates the file; also set it on an existing one.
    TOKEN_FILE.chmod(0o600)


def load_tokens() -> dict:
    """Load tokens from temp file."""
    if not TOKEN_FILE.exists():
        raise FileNotFoundError("No tokens found. Run 'armadillo-flwr-authenticate' first.")

    with open(TOKEN_FILE) as f:
        return json.load(f)


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Authenticate to Flower nodes")
    parser.add_argument(
        "--config",
        default="flower-nodes.yaml",
        help="Path to node config file"
    )
    args = parser.parse_args()

    authenticate(args.config)

    console.print("\n[green]Ready to run:[/green] armadillo-flwr-run")
