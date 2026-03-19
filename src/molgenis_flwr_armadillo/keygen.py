"""Generate an Ed25519 keypair for FAB signing.

Usage:
    molgenis-flwr-keygen --name <name>

Output:
    <name>.key  — private key (PEM, for signing FABs)
    <name>.pub  — public key (SSH format, for trusted-entities.yaml)
    Prints the derived key_id to stdout.

The public key is written in OpenSSH format because Flower's native
``--trusted-entities`` verification uses ``load_ssh_public_key``.
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
    """Generate keypair, write key files, return key_id."""
    private_key, public_key = generate_keypair()

    priv_pem = private_key.private_bytes(
        Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()
    )
    pub_ssh = public_key.public_bytes(Encoding.OpenSSH, PublicFormat.OpenSSH)

    Path(f"{name}.key").write_bytes(priv_pem)
    Path(f"{name}.pub").write_bytes(pub_ssh)

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
