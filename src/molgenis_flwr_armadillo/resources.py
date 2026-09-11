"""CLI for listing accessible projects and resources on Armadillo nodes."""

import argparse
import sys

import yaml
from rich.console import Console
from rich.tree import Tree

from molgenis_flwr_armadillo.authenticate import load_node_urls, load_tokens
from molgenis_flwr_armadillo.helpers import (
    check_access,
    list_projects,
    list_resources,
    sanitize_url,
)

console = Console()


def build_resource_tree(url: str, token: str, only_project: str | None) -> Tree:
    """Return a tree of the projects (and their resources) visible at one node."""
    if only_project:
        check_access(url, token, only_project)
        projects = [only_project]
    else:
        projects = list_projects(url, token)

    tree = Tree(f"[cyan]{url}[/cyan]")
    if not projects:
        tree.add("[yellow]no accessible projects[/yellow]")
    for project in sorted(projects):
        branch = tree.add(f"[green]{project}[/green]")
        try:
            resources = list_resources(url, token, project)
        except RuntimeError as e:
            branch.add(f"[red]Error: {e}[/red]")
            continue
        for resource in sorted(resources):
            branch.add(resource)
        if not resources:
            branch.add("[dim]no resources[/dim]")
    return tree


def main() -> None:
    """CLI entry point for armadillo-flwr-resources."""
    parser = argparse.ArgumentParser(
        description="List the projects you can access as a researcher, and their resources, "
        "on each Armadillo node"
    )
    parser.add_argument("--config", default="flower-nodes.yaml", help="Path to node config file")
    parser.add_argument("--project", help="Show resources for a specific project only")
    args = parser.parse_args()

    try:
        tokens = load_tokens()
        urls = load_node_urls(args.config)
    except (FileNotFoundError, ValueError, yaml.YAMLError) as e:
        console.print(f"[red]{e}[/red]")
        sys.exit(1)

    for url in urls:
        console.rule(f"[bold blue]{url}[/bold blue]")
        token = tokens.get(sanitize_url(url))
        if not token:
            console.print("  [red]No token for this node. Run armadillo-flwr-authenticate.[/red]")
            continue
        try:
            console.print(build_resource_tree(url, token, args.project))
        except RuntimeError as e:
            console.print(f"  [red]Error: {e}[/red]")
        console.print()
