"""Tests for flwr run wrapper."""

import base64
import json
import stat
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from molgenis_flwr_armadillo.helpers import TOKENS_KEY
from molgenis_flwr_armadillo.run import build_command, main, write_run_config

FAKE_TOKENS = {
    "node1-example-com": "eyJtoken1",
    "node2-example-com": "eyJtoken2",
}


def _read_bundle(path: Path) -> dict:
    """Decode the armadillo-tokens value from a run-config TOML file."""
    key, _, value = path.read_text().strip().partition(" = ")
    assert key == TOKENS_KEY
    return json.loads(base64.b64decode(value.strip('"')).decode())


class TestWriteRunConfig:
    """Tests for write_run_config."""

    def test_writes_token_bundle(self):
        path = write_run_config(FAKE_TOKENS)
        try:
            assert path.suffix == ".toml"
            assert _read_bundle(path) == FAKE_TOKENS
        finally:
            path.unlink()

    def test_file_is_private(self):
        path = write_run_config(FAKE_TOKENS)
        try:
            assert stat.S_IMODE(path.stat().st_mode) == 0o600
        finally:
            path.unlink()


class TestBuildCommand:
    """Tests for build_command."""

    def test_points_run_config_at_file(self):
        cmd = build_command([], Path("/tmp/x.toml"))
        assert cmd == ["flwr", "run", "--run-config", "/tmp/x.toml"]

    def test_forwards_user_args(self):
        cmd = build_command([".", "federation", "--stream"], Path("/tmp/x.toml"))
        assert cmd[2:5] == [".", "federation", "--stream"]


class TestMain:
    """Tests for main CLI entry point."""

    @patch("molgenis_flwr_armadillo.run.subprocess.run")
    @patch("molgenis_flwr_armadillo.run.load_tokens", return_value=FAKE_TOKENS)
    @patch("molgenis_flwr_armadillo.run.console")
    def test_calls_flwr_run_and_removes_config_file(self, mock_console, mock_load, mock_run):
        mock_run.return_value = MagicMock(returncode=0)

        with patch.object(sys, "argv", ["prog", ".", "fed1"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 0

        cmd = mock_run.call_args[0][0]
        assert cmd[0:2] == ["flwr", "run"]
        assert not Path(cmd[cmd.index("--run-config") + 1]).exists()

    @patch("molgenis_flwr_armadillo.run.subprocess.run")
    @patch("molgenis_flwr_armadillo.run.load_tokens", return_value=FAKE_TOKENS)
    @patch("molgenis_flwr_armadillo.run.console")
    def test_propagates_return_code(self, mock_console, mock_load, mock_run):
        mock_run.return_value = MagicMock(returncode=1)

        with patch.object(sys, "argv", ["prog"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1

    @patch(
        "molgenis_flwr_armadillo.run.load_tokens",
        side_effect=FileNotFoundError("No tokens found"),
    )
    @patch("molgenis_flwr_armadillo.run.console")
    def test_exits_on_missing_tokens(self, mock_console, mock_load):
        with patch.object(sys, "argv", ["prog"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1
