"""Tests for run functions."""

from unittest.mock import MagicMock, patch, call

import pytest


class TestRun:
    """Tests for run function."""

    @patch("molgenis_flwr_armadillo.run.subprocess.run")
    @patch("molgenis_flwr_armadillo.run.load_tokens")
    @patch("molgenis_flwr_armadillo.run.console")
    @patch("molgenis_flwr_armadillo.run.sys.exit")
    def test_builds_correct_command(self, mock_exit, mock_console, mock_load, mock_subprocess):
        """Should build correct flwr run command with tokens."""
        from molgenis_flwr_armadillo.run import run

        mock_load.return_value = {
            "token-demo": "abc123",
            "token-localhost": "xyz789",
        }
        mock_subprocess.return_value = MagicMock(returncode=0)

        run(app_dir="my-app")

        # Check subprocess was called with correct command
        mock_subprocess.assert_called_once()
        cmd = mock_subprocess.call_args[0][0]

        assert cmd[0] == "flwr"
        assert cmd[1] == "run"
        assert cmd[2] == "my-app"
        assert cmd[3] == "--run-config"
        # run_config should contain both tokens
        assert "token-demo" in cmd[4]
        assert "token-localhost" in cmd[4]

    @patch("molgenis_flwr_armadillo.run.subprocess.run")
    @patch("molgenis_flwr_armadillo.run.load_tokens")
    @patch("molgenis_flwr_armadillo.run.console")
    @patch("molgenis_flwr_armadillo.run.sys.exit")
    def test_passes_extra_args(self, mock_exit, mock_console, mock_load, mock_subprocess):
        """Should pass extra args to flwr run."""
        from molgenis_flwr_armadillo.run import run

        mock_load.return_value = {"token-demo": "abc"}
        mock_subprocess.return_value = MagicMock(returncode=0)

        run(app_dir="my-app", extra_args=["--stream", "--federation", "local"])

        cmd = mock_subprocess.call_args[0][0]

        assert "--stream" in cmd
        assert "--federation" in cmd
        assert "local" in cmd

    @patch("molgenis_flwr_armadillo.run.subprocess.run")
    @patch("molgenis_flwr_armadillo.run.load_tokens")
    @patch("molgenis_flwr_armadillo.run.console")
    @patch("molgenis_flwr_armadillo.run.sys.exit")
    def test_exits_with_subprocess_returncode(self, mock_exit, mock_console, mock_load, mock_subprocess):
        """Should exit with subprocess return code."""
        from molgenis_flwr_armadillo.run import run

        mock_load.return_value = {"token-demo": "abc"}
        mock_subprocess.return_value = MagicMock(returncode=42)

        run(app_dir="my-app")

        mock_exit.assert_called_once_with(42)

    @patch("molgenis_flwr_armadillo.run.console")
    @patch("molgenis_flwr_armadillo.run.load_tokens")
    def test_exits_on_missing_tokens(self, mock_load, mock_console):
        """Should exit with code 1 when tokens file is missing."""
        from molgenis_flwr_armadillo.run import run

        mock_load.side_effect = FileNotFoundError("No tokens found")

        with pytest.raises(SystemExit) as exc_info:
            run(app_dir="my-app")

        assert exc_info.value.code == 1

    @patch("molgenis_flwr_armadillo.run.subprocess.run")
    @patch("molgenis_flwr_armadillo.run.load_tokens")
    @patch("molgenis_flwr_armadillo.run.console")
    @patch("molgenis_flwr_armadillo.run.sys.exit")
    def test_default_app_dir_is_current(self, mock_exit, mock_console, mock_load, mock_subprocess):
        """Should use current directory as default app_dir."""
        from molgenis_flwr_armadillo.run import run

        mock_load.return_value = {"token-demo": "abc"}
        mock_subprocess.return_value = MagicMock(returncode=0)

        run()

        cmd = mock_subprocess.call_args[0][0]
        assert cmd[2] == "."

    @patch("molgenis_flwr_armadillo.run.subprocess.run")
    @patch("molgenis_flwr_armadillo.run.load_tokens")
    @patch("molgenis_flwr_armadillo.run.console")
    @patch("molgenis_flwr_armadillo.run.sys.exit")
    def test_quotes_token_values(self, mock_exit, mock_console, mock_load, mock_subprocess):
        """Should quote token values in run-config."""
        from molgenis_flwr_armadillo.run import run

        mock_load.return_value = {"token-demo": "value with spaces"}
        mock_subprocess.return_value = MagicMock(returncode=0)

        run(app_dir="my-app")

        cmd = mock_subprocess.call_args[0][0]
        run_config = cmd[4]

        # Value should be quoted
        assert 'token-demo="value with spaces"' in run_config


class TestMain:
    """Tests for main CLI entry point."""

    @patch("molgenis_flwr_armadillo.run.run")
    def test_parses_app_dir(self, mock_run):
        """Should parse --app-dir argument."""
        from molgenis_flwr_armadillo.run import main
        import sys

        with patch.object(sys, "argv", ["prog", "--app-dir", "my-app"]):
            main()

        mock_run.assert_called_once_with("my-app", [])

    @patch("molgenis_flwr_armadillo.run.run")
    def test_passes_extra_args_after_separator(self, mock_run):
        """Should pass args after -- to flwr run."""
        from molgenis_flwr_armadillo.run import main
        import sys

        with patch.object(sys, "argv", ["prog", "--app-dir", "my-app", "--", "--stream"]):
            main()

        mock_run.assert_called_once_with("my-app", ["--stream"])

    @patch("molgenis_flwr_armadillo.run.run")
    def test_default_app_dir(self, mock_run):
        """Should use default app_dir when not specified."""
        from molgenis_flwr_armadillo.run import main
        import sys

        with patch.object(sys, "argv", ["prog"]):
            main()

        mock_run.assert_called_once_with(".", [])