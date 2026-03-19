"""Verified SuperNode wrapper.

Closes the ``valid_license`` bypass in Flower's native FAB verification.

Flower's SuperLink discards verification metadata for directly submitted
FABs, so supernodes skip signature checking because ``valid_license`` is
missing.  This wrapper patches ``_pull_and_store_message`` to inject
``valid_license`` into every FAB, ensuring Flower's native
``--trusted-entities`` verification always runs.

All actual cryptographic verification is handled by Flower's own code.

Usage in a verified SuperNode Docker container::

    ENTRYPOINT ["python", "-m", "molgenis_flwr_armadillo.supernode_verify"]

All arguments (including ``--trusted-entities``) are forwarded to the
real ``flower-supernode``.
"""

from __future__ import annotations

import logging
import sys

log = logging.getLogger("molgenis_flwr_armadillo.supernode_verify")


def _patch_pull_and_store() -> None:
    """Ensure every FAB has valid_license set so Flower's native check runs."""
    import flwr.supernode.start_client_internal as sci

    original_fn = sci._pull_and_store_message

    def patched_pull_and_store(
        state, ffs, object_store, node_config,
        receive, get_run, get_fab, pull_object, confirm_message_received,
        **kwargs,
    ):
        def get_fab_with_valid_license(fab_hash, run_id):
            fab = get_fab(fab_hash, run_id)
            if "valid_license" not in fab.verifications:
                fab.verifications["valid_license"] = "Valid"
            return fab

        return original_fn(
            state, ffs, object_store, node_config,
            receive, get_run, get_fab_with_valid_license, pull_object,
            confirm_message_received,
            **kwargs,
        )

    sci._pull_and_store_message = patched_pull_and_store


def main() -> None:
    """Entry point: patch, then start the standard flower-supernode."""
    logging.basicConfig(level=logging.INFO)

    _patch_pull_and_store()
    log.info("Patched SuperNode to enforce FAB verification (valid_license bypass closed)")

    sys.argv = ["flower-supernode"] + sys.argv[1:]
    from flwr.supernode.cli.flower_supernode import flower_supernode

    flower_supernode()


if __name__ == "__main__":
    main()