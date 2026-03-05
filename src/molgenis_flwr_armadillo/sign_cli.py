"""Build a FAB from an app directory, sign it, and write a .sfab file.

Usage:
    molgenis-flwr-sign --app-dir <path> --private-key <key.pem> --output <study.sfab>

The .sfab file contains the FAB bytes (base64-encoded), its SHA-256 hash,
and the signing verifications dict — ready for submission via molgenis-flwr-run.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path

from cryptography.hazmat.primitives.serialization import load_pem_private_key
from flwr.cli.build import build_fab_from_disk

from molgenis_flwr_armadillo.signing import sign_fab


def sign_app(app_dir: str, private_key_path: str, output_path: str) -> None:
    """Build FAB from app dir, sign it, write .sfab file."""
    fab_bytes = build_fab_from_disk(Path(app_dir))
    fab_hash = hashlib.sha256(fab_bytes).hexdigest()

    private_key = load_pem_private_key(
        Path(private_key_path).read_bytes(), password=None
    )
    verifications = sign_fab(fab_bytes, private_key)

    sfab = {
        "fab_hash": fab_hash,
        "fab_content": base64.b64encode(fab_bytes).decode(),
        "verifications": verifications,
    }
    with open(output_path, "w") as f:
        json.dump(sfab, f, indent=2)


def main() -> None:
    parser = argparse.ArgumentParser(description="Sign a Flower app as a .sfab file")
    parser.add_argument("--app-dir", required=True, help="Path to the Flower app directory")
    parser.add_argument("--private-key", required=True, help="Path to Ed25519 private key (PEM)")
    parser.add_argument("--output", required=True, help="Output path for the .sfab file")
    args = parser.parse_args()

    sign_app(args.app_dir, args.private_key, args.output)
    print(f"Signed FAB written to {args.output}")


if __name__ == "__main__":
    main()
