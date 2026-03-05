"""SuperNode verification wrapper (defense in depth).

Patches ``_pull_and_store_message`` to verify FAB signatures after
``get_fab()`` returns but before extraction and execution.

Even if something bypasses the SuperLink check, this second layer
ensures the SuperNode never runs untrusted code.

Usage in a verified SuperNode Docker container::

    ENTRYPOINT ["python", "-m", "molgenis_flwr_armadillo.supernode_verify",
                "--trusted-entities", "/app/trusted-entities.yaml"]

All other arguments are forwarded to the real ``flower-supernode``.
"""

from __future__ import annotations

import logging
import sys

import yaml
from cryptography.hazmat.primitives.serialization import load_pem_public_key

from molgenis_flwr_armadillo.signing import verify_fab

log = logging.getLogger("molgenis_flwr_armadillo.supernode_verify")


def load_trusted_keys(path: str) -> dict:
    """Load trusted-entities.yaml → {key_id: Ed25519PublicKey}."""
    with open(path) as f:
        raw = yaml.safe_load(f)
    return {
        kid: load_pem_public_key(pem.encode())
        for kid, pem in raw.items()
    }


def _make_verifying_get_fab(original_get_fab, trusted_keys):
    """Wrap get_fab to verify the returned Fab before handing it back."""

    def verifying_get_fab(fab_hash, run_id):
        fab = original_get_fab(fab_hash, run_id)
        if not verify_fab(fab.content, fab.verifications, trusted_keys):
            msg = f"REJECTED FAB {fab_hash}: signature verification failed"
            log.error(msg)
            raise RuntimeError(msg)
        log.info("FAB %s signature verified for run %d", fab_hash, run_id)
        return fab

    return verifying_get_fab


def _patch_pull_and_store(trusted_keys: dict) -> None:
    """Monkey-patch _pull_and_store_message to wrap its get_fab argument."""
    import flwr.supernode.start_client_internal as sci

    original_fn = sci._pull_and_store_message

    def patched_pull_and_store(
        state, ffs, object_store, node_config,
        receive, get_run, get_fab, pull_object, confirm_message_received,
    ):
        wrapped_get_fab = _make_verifying_get_fab(get_fab, trusted_keys)
        return original_fn(
            state, ffs, object_store, node_config,
            receive, get_run, wrapped_get_fab, pull_object,
            confirm_message_received,
        )

    sci._pull_and_store_message = patched_pull_and_store


def main() -> None:
    """Entry point: parse --trusted-entities, patch, then run supernode."""
    args = sys.argv[1:]

    trusted_entities_path = None
    forwarded = []
    i = 0
    while i < len(args):
        if args[i] == "--trusted-entities" and i + 1 < len(args):
            trusted_entities_path = args[i + 1]
            i += 2
        else:
            forwarded.append(args[i])
            i += 1

    if not trusted_entities_path:
        print("Error: --trusted-entities <path> is required", file=sys.stderr)
        sys.exit(1)

    logging.basicConfig(level=logging.INFO)
    trusted_keys = load_trusted_keys(trusted_entities_path)
    log.info("Loaded %d trusted key(s) from %s", len(trusted_keys), trusted_entities_path)

    _patch_pull_and_store(trusted_keys)

    sys.argv = ["flower-supernode"] + forwarded
    from flwr.supernode.cli.flower_supernode import flower_supernode

    flower_supernode()


if __name__ == "__main__":
    main()
