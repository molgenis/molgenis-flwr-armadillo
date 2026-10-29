"""Tests for the armadillo-flwr-superexec command."""

import sys
from unittest.mock import patch

import pytest

from molgenis_flwr_armadillo.verified_exec_plugin import VerifiedClientAppExecPlugin
from molgenis_flwr_armadillo.verified_superexec import build_parser, main


def test_passes_whitelist_path_and_connection_settings():
    argv = ["prog", "--appio-api-address", "sn:9094", "--fab-whitelist", "/app/w.yaml", "--insecure"]

    with patch.object(sys, "argv", argv), patch(
        "molgenis_flwr_armadillo.verified_superexec.run_superexec"
    ) as mock_run:
        main()

    kwargs = mock_run.call_args.kwargs
    assert kwargs["plugin_class"] is VerifiedClientAppExecPlugin
    assert kwargs["appio_api_address"] == "sn:9094"
    assert kwargs["insecure"] is True
    assert kwargs["root_certificates_path"] is None
    assert kwargs["plugin_config"] == {"fab_whitelist_path": "/app/w.yaml"}


@pytest.mark.parametrize(
    "argv",
    [
        ["--appio-api-address", "sn:9094"],
        ["--appio-api-address", "sn:9094", "--fab-whitelist", "w.yaml", "--plugin-type", "clientapp"],
    ],
)
def test_rejects_missing_or_unknown_arguments(argv):
    with pytest.raises(SystemExit):
        build_parser().parse_args(argv)
