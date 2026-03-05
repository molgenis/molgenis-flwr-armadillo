"""Tests for submit_signed_fab and CLI."""

import base64
import json
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest


def _make_sfab(fab_hash="abc123", fab_content=b"fake-fab", verifications=None):
    """Create a temporary .sfab file and return its path."""
    if verifications is None:
        verifications = {"fpk_test1234": '{"signature": "sig", "signed_at": 100}'}

    sfab = {
        "fab_hash": fab_hash,
        "fab_content": base64.b64encode(fab_content).decode(),
        "verifications": verifications,
    }
    fd, path = tempfile.mkstemp(suffix=".sfab")
    with os.fdopen(fd, "w") as f:
        json.dump(sfab, f)
    return path


class TestSubmitSignedFab:
    """Tests for submit_signed_fab function."""

    @patch("molgenis_flwr_armadillo.run.grpc")
    def test_loads_sfab_and_submits(self, mock_grpc):
        """Should load .sfab, create Fab, and call StartRun."""
        from molgenis_flwr_armadillo.run import submit_signed_fab

        mock_channel = MagicMock()
        mock_grpc.insecure_channel.return_value = mock_channel
        mock_stub = MagicMock()
        mock_stub.StartRun.return_value = MagicMock(run_id=42)

        with patch("molgenis_flwr_armadillo.run.ControlStub", return_value=mock_stub):
            sfab_path = _make_sfab()
            try:
                run_id = submit_signed_fab(sfab_path, "localhost:9093")
            finally:
                os.unlink(sfab_path)

        assert run_id == 42
        mock_grpc.insecure_channel.assert_called_once_with("localhost:9093")
        mock_stub.StartRun.assert_called_once()

    @patch("molgenis_flwr_armadillo.run.grpc")
    def test_passes_config_overrides(self, mock_grpc):
        """Should parse and pass config overrides."""
        from molgenis_flwr_armadillo.run import submit_signed_fab

        mock_channel = MagicMock()
        mock_grpc.insecure_channel.return_value = mock_channel
        mock_stub = MagicMock()
        mock_stub.StartRun.return_value = MagicMock(run_id=1)

        with patch("molgenis_flwr_armadillo.run.ControlStub", return_value=mock_stub):
            with patch("molgenis_flwr_armadillo.run.parse_config_args") as mock_parse:
                mock_parse.return_value = {"key": "val"}
                sfab_path = _make_sfab()
                try:
                    submit_signed_fab(
                        sfab_path, "localhost:9093", ['key="val"']
                    )
                finally:
                    os.unlink(sfab_path)

                mock_parse.assert_called_once_with(['key="val"'])

    @patch("molgenis_flwr_armadillo.run.grpc")
    def test_decodes_fab_content(self, mock_grpc):
        """Should base64-decode fab_content from .sfab."""
        from molgenis_flwr_armadillo.run import submit_signed_fab

        mock_channel = MagicMock()
        mock_grpc.insecure_channel.return_value = mock_channel
        mock_stub = MagicMock()
        mock_stub.StartRun.return_value = MagicMock(run_id=1)

        original_content = b"real-fab-bytes-here"

        with patch("molgenis_flwr_armadillo.run.ControlStub", return_value=mock_stub):
            with patch("molgenis_flwr_armadillo.run.fab_to_proto") as mock_fab_to_proto:
                mock_fab_to_proto.return_value = MagicMock()
                with patch("molgenis_flwr_armadillo.run.StartRunRequest"):
                    sfab_path = _make_sfab(fab_content=original_content)
                    try:
                        submit_signed_fab(sfab_path, "localhost:9093")
                    finally:
                        os.unlink(sfab_path)

                    # Check the Fab passed to fab_to_proto has decoded content
                    fab_arg = mock_fab_to_proto.call_args[0][0]
                    assert fab_arg.content == original_content

    @patch("molgenis_flwr_armadillo.run.grpc")
    def test_closes_channel(self, mock_grpc):
        """Should close the gRPC channel after use."""
        from molgenis_flwr_armadillo.run import submit_signed_fab

        mock_channel = MagicMock()
        mock_grpc.insecure_channel.return_value = mock_channel
        mock_stub = MagicMock()
        mock_stub.StartRun.return_value = MagicMock(run_id=1)

        with patch("molgenis_flwr_armadillo.run.ControlStub", return_value=mock_stub):
            sfab_path = _make_sfab()
            try:
                submit_signed_fab(sfab_path, "localhost:9093")
            finally:
                os.unlink(sfab_path)

        mock_channel.close.assert_called_once()

    def test_raises_on_missing_sfab(self):
        """Should raise FileNotFoundError for missing .sfab file."""
        from molgenis_flwr_armadillo.run import submit_signed_fab

        with pytest.raises(FileNotFoundError):
            submit_signed_fab("/nonexistent/path.sfab", "localhost:9093")


class TestMain:
    """Tests for main CLI entry point."""

    @patch("molgenis_flwr_armadillo.run.submit_signed_fab")
    @patch("molgenis_flwr_armadillo.run.console")
    def test_parses_required_args(self, mock_console, mock_submit):
        """Should parse --signed-fab and --federation-address."""
        from molgenis_flwr_armadillo.run import main
        import sys

        mock_submit.return_value = 42
        sfab_path = _make_sfab()

        try:
            with patch.object(
                sys,
                "argv",
                ["prog", "--signed-fab", sfab_path, "--federation-address", "host:9093"],
            ):
                main()
        finally:
            os.unlink(sfab_path)

        mock_submit.assert_called_once_with(sfab_path, "host:9093", None)

    @patch("molgenis_flwr_armadillo.run.submit_signed_fab")
    @patch("molgenis_flwr_armadillo.run.console")
    def test_handles_grpc_error(self, mock_console, mock_submit):
        """Should exit 1 on gRPC error."""
        from molgenis_flwr_armadillo.run import main
        import sys
        import grpc

        error = grpc.RpcError()
        error.code = lambda: grpc.StatusCode.PERMISSION_DENIED
        error.details = lambda: "FAB not signed"
        mock_submit.side_effect = error

        sfab_path = _make_sfab()
        try:
            with patch.object(
                sys,
                "argv",
                ["prog", "--signed-fab", sfab_path, "--federation-address", "host:9093"],
            ):
                with pytest.raises(SystemExit) as exc_info:
                    main()
                assert exc_info.value.code == 1
        finally:
            os.unlink(sfab_path)
