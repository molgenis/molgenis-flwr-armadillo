"""Generate an Ed25519 keypair for FAB signing.

Usage:
    molgenis-flwr-keygen --name <name>

Output:
    <name>.key  — private key (PEM)
    <name>.pub  — public key (PEM)
    Prints the derived key_id to stdout.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

from molgenis_flwr_armadillo.signing import derive_key_id, generate_keypair


def keygen(name: str) -> str:
    """Generate keypair, write PEM files, return key_id."""
    private_key, public_key = generate_keypair()

    priv_pem = private_key.private_bytes(
        Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()
    )
    pub_pem = public_key.public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)

    Path(f"{name}.key").write_bytes(priv_pem)
    Path(f"{name}.pub").write_bytes(pub_pem)

    return derive_key_id(public_key)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Ed25519 keypair for FAB signing")
    parser.add_argument("--name", required=True, help="Base name for output files (e.g. /tmp/steward)")
    args = parser.parse_args()

    key_id = keygen(args.name)
    print(f"Key ID: {key_id}")
    print(f"Private key: {args.name}.key")
    print(f"Public key:  {args.name}.pub")


if __name__ == "__main__":
    main()
