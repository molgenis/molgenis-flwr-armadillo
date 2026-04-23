"""CLI for listing accessible projects and resources on Armadillo nodes."""

import argparse

from rich.console import Console
from rich.table import Table
from rich.tree import Tree

from molgenis_flwr_armadillo.authenticate import load_tokens
from molgenis_flwr_armadillo.helpers import list_projects, list_resources

console = Console()


def main():
    """CLI entry point for armadillo-flwr-resources."""
    parser = argparse.ArgumentParser(
        description="List projects and resources accessible on Armadillo nodes"
    )
    parser.add_argument(
        "--project",
        help="Show resources for a specific project only",
    )
    args = parser.parse_args()

    tokens = load_tokens()

    # Extract node names and their URLs/tokens
    nodes = {}
    for key, value in tokens.items():
        if key.startswith("url-"):
            node_name = key[4:]
            nodes.setdefault(node_name, {})["url"] = value
        elif key.startswith("token-"):
            node_name = key[6:]
            nodes.setdefault(node_name, {})["token"] = value

    if not nodes:
        console.print("[red]No nodes found in token file.[/red]")
        return

    for node_name, node in nodes.items():
        url = node.get("url", "")
        token = node.get("token", "")

        if not url or not token:
            console.print(f"[red]{node_name}: missing URL or token[/red]")
            continue

        console.rule(f"[bold blue]{node_name}[/bold blue] ({url})")

        try:
            projects = list_projects(url, token)
        except RuntimeError as e:
            console.print(f"  [red]Error: {e}[/red]")
            continue

        if not projects:
            console.print("  [yellow]No accessible projects[/yellow]")
            continue

        if args.project:
            if args.project not in projects:
                console.print(
                    f"  [red]No access to project '{args.project}'[/red]"
                )
                console.print(
                    f"  Available projects: {', '.join(projects)}"
                )
                continue
            projects = [args.project]

        tree = Tree(f"[cyan]{node_name}[/cyan]")
        for project in sorted(projects):
            branch = tree.add(f"[green]{project}[/green]")
            try:
                resources = list_resources(url, token, project)
                if resources:
                    for resource in sorted(resources):
                        branch.add(resource)
                else:
                    branch.add("[dim]no resources[/dim]")
            except RuntimeError as e:
                branch.add(f"[red]Error: {e}[/red]")

        console.print(tree)
        console.print()
