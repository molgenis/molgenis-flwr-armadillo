"""`armadillo-flwr-superexec` command.

Runs Flower's SuperExec with :class:`VerifiedClientAppExecPlugin` instead of
the stock ``ClientAppExecPlugin``, so only FAB-hash-whitelisted apps launch.
Takes only the arguments Armadillo passes; anything else is rejected.
"""

import argparse
from logging import INFO

from flwr.common.logger import log
from flwr.proto.clientappio_pb2_grpc import ClientAppIoStub
from flwr.supercore.superexec.run_superexec import run_superexec

from molgenis_flwr_armadillo.verified_exec_plugin import VerifiedClientAppExecPlugin


def main() -> None:
    """Run `armadillo-flwr-superexec` command."""
    args = build_parser().parse_args()
    log(INFO, "Starting Armadillo Flower SuperExec (FAB whitelist enforced)")
    run_superexec(
        plugin_class=VerifiedClientAppExecPlugin,
        stub_class=ClientAppIoStub,
        appio_api_address=args.appio_api_address,
        insecure=args.insecure,
        root_certificates_path=args.root_certificates,
        plugin_config={"fab_whitelist_path": args.fab_whitelist},
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the `armadillo-flwr-superexec` argument parser."""
    parser = argparse.ArgumentParser(
        description="Run Armadillo's FAB-whitelisted Flower SuperExec.",
    )
    parser.add_argument(
        "--appio-api-address", required=True, help="Address of the SuperNode's AppIO API"
    )
    parser.add_argument(
        "--fab-whitelist",
        required=True,
        help="YAML file of approved {fab_id, fab_version, fab_hash} entries",
    )
    parser.add_argument(
        "--insecure", action="store_true", help="Connect to the AppIO API without TLS"
    )
    parser.add_argument(
        "--root-certificates",
        metavar="ROOT_CERT",
        help="PEM root CA certificate used to verify the AppIO API's TLS certificate",
    )
    return parser
