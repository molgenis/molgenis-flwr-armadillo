"""CLIs for reviewing a Flower App Bundle and whitelisting it on an Armadillo container.

Two separate commands, because a review can take hours: armadillo-flwr-review-app
downloads and unpacks the app, and armadillo-flwr-approve-app later sends the
hash of that same file to Armadillo.
"""

import argparse
import getpass
import sys
import zipfile
from pathlib import Path
from typing import NoReturn

import click
import requests
import yaml
from flwr.cli.config_utils import get_fab_metadata
from flwr.cli.install import install_from_fab
from flwr.cli.utils import get_sha256_hash
from flwr.supercore.constant import PLATFORM_API_URL
from flwr.supercore.utils import get_flwr_home, parse_app_spec, request_download_link
from rich.console import Console

from molgenis_flwr_armadillo._http import describe_http_error
from molgenis_flwr_armadillo.authenticate import load_tokens
from molgenis_flwr_armadillo.helpers import sanitize_url

console = Console()

REVIEW_DIR = get_flwr_home() / "reviews"

# Errors flwr and requests raise for an app that cannot be downloaded or is not a valid FAB.
FAB_ERRORS = (ValueError, KeyError, zipfile.BadZipFile, click.ClickException, requests.RequestException)


def pull_fab(app_spec: str, dest_dir: Path) -> Path:
    """Download a FAB from Flower Hub and return the saved .fab path."""
    app_id, app_version = parse_app_spec(app_spec)
    url, _, note = request_download_link(
        app_id, app_version, f"{PLATFORM_API_URL}/hub/fetch-fab", "fab_url"
    )
    if note:
        console.print(f"[yellow]Note: {note}[/yellow]")

    response = requests.get(url, timeout=60)
    response.raise_for_status()

    dest_dir.mkdir(parents=True, exist_ok=True)
    fab_path = dest_dir / (app_id.lstrip("@").replace("/", "-") + ".fab")
    fab_path.write_bytes(response.content)
    return fab_path


def unpack_for_review(fab_path: Path, review_dir: Path) -> Path:
    """Unpack the FAB so the reviewer can read its code; return the app directory."""
    return install_from_fab(fab_path.read_bytes(), review_dir, skip_prompt=True)


def build_whitelist_entry(fab_path: Path) -> dict:
    """Return the ``{fab_id, fab_version, fab_hash}`` whitelist entry for a FAB file.

    Metadata and hash come from the same file, so they always describe the same app.
    """
    fab_id, fab_version = get_fab_metadata(fab_path)
    fab_hash = get_sha256_hash(fab_path)
    return {"fab_id": fab_id, "fab_version": fab_version, "fab_hash": fab_hash}


def armadillo_auth(armadillo: str, user: str | None) -> dict:
    """Return the request arguments for authenticating to Armadillo.

    Basic auth when a user is given (asks for the password), otherwise the saved OIDC token.
    """
    if user:
        return {"auth": (user, getpass.getpass(f"Password for {user} at {armadillo}: "))}

    try:
        token = load_tokens().get(sanitize_url(armadillo))
    except FileNotFoundError:
        token = None
    if not token:
        raise RuntimeError(
            f"No token for {armadillo}. Run armadillo-flwr-authenticate with an admin "
            f"account, or pass --user for basic auth."
        )
    return {"headers": {"Authorization": f"Bearer {token}"}}


def add_to_whitelist(armadillo: str, container: str, entry: dict, auth: dict) -> None:
    """POST the entry to the container's whitelist on Armadillo."""
    endpoint = f"{armadillo.rstrip('/')}/containers/{container}/fab-whitelist"
    response = requests.post(
        endpoint,
        json={
            "fabId": entry["fab_id"],
            "fabVersion": entry["fab_version"],
            "fabHash": entry["fab_hash"],
        },
        timeout=30,
        **auth,
    )
    if response.status_code == 401:
        raise RuntimeError(
            f"Token expired or invalid for {armadillo}. Re-run armadillo-flwr-authenticate "
            f"with an admin account, or pass --user."
        )
    if response.status_code == 403:
        raise RuntimeError(f"This account has no admin rights on {armadillo}.")
    if response.status_code == 404:
        raise RuntimeError(f"Container '{container}' not found on {armadillo}.")
    if not response.ok:
        raise RuntimeError(describe_http_error(response, endpoint))


def fetch_fab(app: str) -> Path:
    """Return the path of the app's .fab: a local file as given, or downloaded from Flower Hub."""
    return Path(app) if Path(app).is_file() else pull_fab(app, REVIEW_DIR)


def show_entry(entry: dict) -> None:
    """Print the whitelist entry."""
    console.print(yaml.safe_dump([entry], sort_keys=False))


def confirm_approval(entry: dict) -> bool:
    """Show the entry and the consequence of approving, and return whether the user typed APPROVE."""
    show_entry(entry)
    console.print(
        "[yellow]Adding an app to the whitelist means that approved researchers can run it "
        "against your local data.[/yellow]"
    )
    answer = console.input("Type APPROVE to add this entry to the whitelist: ")
    return answer.strip().upper() == "APPROVE"


def exit_with_error(message: str) -> NoReturn:
    """Print the message in red and exit with status 1."""
    console.print(f"[red]{message}[/red]")
    sys.exit(1)


def review_main() -> None:
    """CLI entry point for armadillo-flwr-review-app: download, check and unpack an app."""
    parser = argparse.ArgumentParser(description="Download and unpack a Flower App Bundle for review.")
    parser.add_argument("app", help="Hub app spec (@account/app[==1.0.0]) or path to a .fab file")
    args = parser.parse_args()

    try:
        fab_path = fetch_fab(args.app)
        entry = build_whitelist_entry(fab_path)
        app_dir = unpack_for_review(fab_path, REVIEW_DIR)
    except FAB_ERRORS as e:
        exit_with_error(str(e))

    console.print(f"Review the app in: [green]{app_dir}[/green]")
    show_entry(entry)
    console.print("When you are satisfied, approve exactly this file with:")
    console.print(f"  armadillo-flwr-approve-app {fab_path} --armadillo <URL> --container <name>")


def approve_main() -> None:
    """CLI entry point for armadillo-flwr-approve-app: add a reviewed .fab's hash to a whitelist."""
    parser = argparse.ArgumentParser(description="Add a reviewed Flower App Bundle to a container's whitelist.")
    parser.add_argument("fab", type=Path, help="The .fab file reviewed with armadillo-flwr-review-app")
    parser.add_argument("--armadillo", required=True, help="Armadillo server URL")
    parser.add_argument("--container", required=True, help="Flower clientapp container name")
    parser.add_argument("--user", help="Basic-auth username (dev/test); default is the saved OIDC token")
    args = parser.parse_args()

    try:
        auth = armadillo_auth(args.armadillo, args.user)
        entry = build_whitelist_entry(args.fab)
    except (RuntimeError, OSError, *FAB_ERRORS) as e:
        exit_with_error(str(e))

    if not confirm_approval(entry):
        console.print("[yellow]Aborted; nothing sent.[/yellow]")
        sys.exit(1)

    try:
        add_to_whitelist(args.armadillo, args.container, entry, auth)
    except (RuntimeError, requests.RequestException) as e:
        exit_with_error(str(e))
    console.print(
        f"[green]✓ {entry['fab_id']} {entry['fab_version']} whitelisted on {args.container}[/green]"
    )
