"""Tests for flwr run wrapper."""

import base64
import json
import sys
from unittest.mock import MagicMock, patch

import pytest

from molgenis_flwr_armadillo.helpers import TOKENS_KEY


FAKE_TOKENS = {
    "token-node1-example-com": "eyJtoken1",
    "url-node1-example-com": "https://node1.example.com",
    "token-node2-example-com": "eyJtoken2",
    "url-node2-example-com": "https://node2.example.com",
}


def _decode_bundle(config_str: str) -> dict:
    """Extract and decode the armadillo-tokens blob from a --run-config string."""
    assert config_str.startswith(f"{TOKENS_KEY}=")
    blob = config_str[len(TOKENS_KEY) + 1:].strip("'")
    return json.loads(base64.b64decode(blob).decode())


class TestBuildCommand:
    """Tests for build_command."""

    @patch("molgenis_flwr_armadillo.run.load_tokens", return_value=FAKE_TOKENS)
    def test_builds_flwr_run_with_tokens(self, mock_load):
        from molgenis_flwr_armadillo.run import build_command

        cmd = build_command([])
        assert cmd[0:2] == ["flwr", "run"]
        assert "--run-config" in cmd
        config_str = cmd[cmd.index("--run-config") + 1]
        bundle = _decode_bundle(config_str)
        assert bundle == {
            "node1-example-com": "eyJtoken1",
            "node2-example-com": "eyJtoken2",
        }

    @patch("molgenis_flwr_armadillo.run.load_tokens", return_value=FAKE_TOKENS)
    def test_excludes_url_keys_from_bundle(self, mock_load):
        from molgenis_flwr_armadillo.run import build_command

        cmd = build_command([])
        bundle = _decode_bundle(cmd[cmd.index("--run-config") + 1])
        # Only the two token entries, keyed by sanitized URL; no url- entries.
        assert bundle == {
            "node1-example-com": "eyJtoken1",
            "node2-example-com": "eyJtoken2",
        }
        assert "https://node1.example.com" not in bundle.values()

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
