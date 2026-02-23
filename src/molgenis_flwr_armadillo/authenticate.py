"""Token management for Flower federated learning with Armadillo."""

import argparse
import json
import tempfile
from pathlib import Path

import requests
import yaml
from molgenis_auth import MolgenisAuthClient
from rich.console import Console
from rich.table import Table

# Console for styled output
console = Console()

# Default token storage location
TOKEN_FILE = Path(tempfile.gettempdir()) / "flwr_tokens.json"


def get_auth_info(armadillo_url: str) -> dict:
    """
    Get auth info from Armadillo server.

    Args:
        armadillo_url: Base URL of Armadillo server

    Returns:
        Dict with 'clientId' and 'issuerUri'
    """
    info_url = f"{armadillo_url.rstrip('/')}/actuator/info"
    response = requests.get(info_url)
    response.raise_for_status()
    return response.json()["auth"]


def authenticate(config_path: str) -> dict:
    """
    Load node config and authenticate to each node.

    Args:
        config_path: Path to YAML config file with node definitions

    Returns:
        Dictionary of {token-nodename: token_value}
    """
    # Load config
    with open(config_path) as f:
        config = yaml.safe_load(f)

    tokens = {}

    for node_name, node_config in config["nodes"].items():
        console.rule(f"[bold blue]{node_name}[/bold blue]")

        # Get auth info from Armadillo server
        url = node_config["url"]

        with console.status(f"Fetching auth info from {url}..."):
            auth_info = get_auth_info(url)

        console.print(f"  URL: [cyan]{url}[/cyan]")
        console.print(f"  Auth server: [cyan]{auth_info['issuerUri']}[/cyan]")

        # Authenticate using discovered settings
        client = MolgenisAuthClient(
            auth_server=auth_info["issuerUri"],
            client_id=auth_info["clientId"],
            scopes="openid offline_access"
        )

        console.print("  [yellow]Opening browser for authentication...[/yellow]")
        auth_result = client.device_flow_auth()

        tokens[f"token-{node_name}"] = auth_result["access_token"]
        console.print(f"  [green]✓ {node_name} authenticated[/green]")

    save_tokens(tokens)

    # Summary table
    console.print()
    table = Table(title="Authenticated Nodes")
    table.add_column("Node", style="cyan")
    table.add_column("Status", style="green")
    for key in tokens.keys():
        node = key.replace("token-", "")
        table.add_row(node, "✓ Ready")
    console.print(table)

    return tokens


def save_tokens(tokens: dict) -> None:
    """Save tokens to temp file."""
    with open(TOKEN_FILE, "w") as f:
        json.dump(tokens, f)
    console.print(f"\n[dim]Tokens saved to {TOKEN_FILE}[/dim]")


def load_tokens() -> dict:
    """Load tokens from temp file."""
    if not TOKEN_FILE.exists():
        raise FileNotFoundError("No tokens found. Run 'molgenis-flwr-authenticate' first.")

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

    console.print("[bold]Molgenis Flower Armadillo[/bold]")
    console.print()

    authenticate(args.config)

    console.print("\n[green]Ready to run:[/green] molgenis-flwr-run")


