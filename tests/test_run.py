"""Tests for flwr run wrapper."""

import sys
from unittest.mock import MagicMock, patch

import pytest


FAKE_TOKENS = {
    "token-node1-example-com": "eyJtoken1",
    "token-node2-example-com": "eyJtoken2",
}


class TestBuildCommand:
    """Tests for build_command."""

    @patch("molgenis_flwr_armadillo.run.load_tokens", return_value=FAKE_TOKENS)
    def test_builds_flwr_run_with_tokens(self, mock_load):
        from molgenis_flwr_armadillo.run import build_command

        cmd = build_command([])
        assert cmd[0:2] == ["flwr", "run"]
        assert "--run-config" in cmd
        config_str = cmd[cmd.index("--run-config") + 1]
        assert 'token-node1-example-com="eyJtoken1"' in config_str
        assert 'token-node2-example-com="eyJtoken2"' in config_str

    @patch("molgenis_flwr_armadillo.run.load_tokens", return_value=FAKE_TOKENS)
    def test_forwards_user_args(self, mock_load):
        from molgenis_flwr_armadillo.run import build_command

        cmd = build_command([".", "federation", "--stream"])
        assert cmd[2:5] == [".", "federation", "--stream"]

    @patch(
        "molgenis_flwr_armadillo.run.load_tokens",
        side_effect=FileNotFoundError("No tokens found"),
    )
    def test_raises_when_no_tokens(self, mock_load):
        from molgenis_flwr_armadillo.run import build_command

        with pytest.raises(FileNotFoundError):
            build_command([])


class TestMain:
    """Tests for main CLI entry point."""

    @patch("molgenis_flwr_armadillo.run.subprocess.run")
    @patch("molgenis_flwr_armadillo.run.load_tokens", return_value=FAKE_TOKENS)
    @patch("molgenis_flwr_armadillo.run.console")
    def test_calls_flwr_run(self, mock_console, mock_load, mock_run):
        from molgenis_flwr_armadillo.run import main

        mock_run.return_value = MagicMock(returncode=0)

        with patch.object(sys, "argv", ["prog", ".", "fed1"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 0

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[0:2] == ["flwr", "run"]

    @patch("molgenis_flwr_armadillo.run.subprocess.run")
    @patch("molgenis_flwr_armadillo.run.load_tokens", return_value=FAKE_TOKENS)
    @patch("molgenis_flwr_armadillo.run.console")
    def test_propagates_return_code(self, mock_console, mock_load, mock_run):
        from molgenis_flwr_armadillo.run import main

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
        from molgenis_flwr_armadillo.run import main

        with patch.object(sys, "argv", ["prog"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1
