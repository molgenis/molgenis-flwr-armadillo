"""Tests for authentication functions."""

import json
import stat
import sys
from unittest.mock import MagicMock, patch

import pytest


class TestGetAuthInfo:
    """Tests for get_auth_info function."""

    @patch("requests.get")
    def test_returns_auth_info(self, mock_get):
        """Should return auth info from Armadillo server."""
        from molgenis_flwr_armadillo.authenticate import get_auth_info

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "auth": {
                "clientId": "test-client",
                "issuerUri": "https://auth.example.com",
            }
        }
        mock_get.return_value = mock_response

        result = get_auth_info("https://armadillo.example.com")

        assert result == {
            "clientId": "test-client",
            "issuerUri": "https://auth.example.com",
        }
        mock_get.assert_called_once_with(
            "https://armadillo.example.com/actuator/info", timeout=30
        )

    @patch("requests.get")
    def test_strips_trailing_slash(self, mock_get):
        """Should strip trailing slash from URL."""
        from molgenis_flwr_armadillo.authenticate import get_auth_info

        mock_response = MagicMock()
        mock_response.json.return_value = {"auth": {"clientId": "x", "issuerUri": "y"}}
        mock_get.return_value = mock_response

        get_auth_info("https://armadillo.example.com/")

        mock_get.assert_called_once_with(
            "https://armadillo.example.com/actuator/info", timeout=30
        )

    @patch("requests.get")
    def test_raises_on_http_error(self, mock_get):
        """Should raise on HTTP error."""
        from molgenis_flwr_armadillo.authenticate import get_auth_info

        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = Exception("HTTP Error")
        mock_get.return_value = mock_response

        with pytest.raises(Exception, match="HTTP Error"):
            get_auth_info("https://armadillo.example.com")


class TestSaveAndLoadTokens:
    """Tests for save_tokens and load_tokens functions."""

    def test_save_and_load_roundtrip(self, tmp_path):
        """Should save and load tokens correctly."""
        # Get the actual module (not the function)
        auth_mod = sys.modules["molgenis_flwr_armadillo.authenticate"]
        from molgenis_flwr_armadillo.authenticate import load_tokens, save_tokens

        # Use a temp file for testing
        test_token_file = tmp_path / "test_tokens.json"
        original_token_file = auth_mod.TOKEN_FILE
        auth_mod.TOKEN_FILE = test_token_file

        try:
            tokens = {
                "token-demo": "abc123",
                "token-localhost": "xyz789",
            }

            # Patch console to avoid output during tests
            with patch.object(auth_mod, "console"):
                save_tokens(tokens)

            loaded = load_tokens()

            assert loaded == tokens
        finally:
            auth_mod.TOKEN_FILE = original_token_file

    def test_load_raises_when_file_missing(self, tmp_path):
        """Should raise FileNotFoundError when token file doesn't exist."""
        auth_mod = sys.modules["molgenis_flwr_armadillo.authenticate"]
        from molgenis_flwr_armadillo.authenticate import load_tokens

        test_token_file = tmp_path / "nonexistent.json"
        original_token_file = auth_mod.TOKEN_FILE
        auth_mod.TOKEN_FILE = test_token_file

        try:
            with pytest.raises(FileNotFoundError, match="No tokens found"):
                load_tokens()
        finally:
            auth_mod.TOKEN_FILE = original_token_file

    def test_save_overwrites_existing(self, tmp_path):
        """Should overwrite existing token file."""
        auth_mod = sys.modules["molgenis_flwr_armadillo.authenticate"]
        from molgenis_flwr_armadillo.authenticate import load_tokens, save_tokens

        test_token_file = tmp_path / "test_tokens.json"
        original_token_file = auth_mod.TOKEN_FILE
        auth_mod.TOKEN_FILE = test_token_file

        try:
            with patch.object(auth_mod, "console"):
                save_tokens({"token-old": "old-value"})
                save_tokens({"token-new": "new-value"})

            loaded = load_tokens()

            assert loaded == {"token-new": "new-value"}
            assert "token-old" not in loaded
        finally:
            auth_mod.TOKEN_FILE = original_token_file

    def test_handles_empty_tokens(self, tmp_path):
        """Should handle empty token dict."""
        auth_mod = sys.modules["molgenis_flwr_armadillo.authenticate"]
        from molgenis_flwr_armadillo.authenticate import load_tokens, save_tokens

        test_token_file = tmp_path / "test_tokens.json"
        original_token_file = auth_mod.TOKEN_FILE
        auth_mod.TOKEN_FILE = test_token_file

        try:
            with patch.object(auth_mod, "console"):
                save_tokens({})

            loaded = load_tokens()

            assert loaded == {}
        finally:
            auth_mod.TOKEN_FILE = original_token_file

    def test_token_file_is_private(self, tmp_path):
        """Should create the file 0600, and tighten a pre-existing looser one."""
        auth_mod = sys.modules["molgenis_flwr_armadillo.authenticate"]
        from molgenis_flwr_armadillo.authenticate import save_tokens

        test_token_file = tmp_path / "test_tokens.json"
        test_token_file.write_text("{}")
        test_token_file.chmod(0o644)
        original_token_file = auth_mod.TOKEN_FILE
        auth_mod.TOKEN_FILE = test_token_file

        try:
            with patch.object(auth_mod, "console"):
                save_tokens({"demo": "abc123"})

            assert stat.S_IMODE(test_token_file.stat().st_mode) == 0o600
        finally:
            auth_mod.TOKEN_FILE = original_token_file

    def test_tokens_are_valid_json(self, tmp_path):
        """Should save tokens as valid JSON."""
        auth_mod = sys.modules["molgenis_flwr_armadillo.authenticate"]
        from molgenis_flwr_armadillo.authenticate import save_tokens

        test_token_file = tmp_path / "test_tokens.json"
        original_token_file = auth_mod.TOKEN_FILE
        auth_mod.TOKEN_FILE = test_token_file

        try:
            tokens = {"token-demo": "value-with-special-chars-!@#$%"}

            with patch.object(auth_mod, "console"):
                save_tokens(tokens)

            # Read raw file and parse as JSON
            with open(test_token_file) as f:
                raw_content = f.read()
                parsed = json.loads(raw_content)

            assert parsed == tokens
        finally:
            auth_mod.TOKEN_FILE = original_token_file


class TestLoadNodeUrls:
    """Tests for load_node_urls function."""

    def test_reads_urls_from_yaml(self, tmp_path):
        from molgenis_flwr_armadillo.authenticate import load_node_urls

        config = tmp_path / "flower-nodes.yaml"
        config.write_text('urls:\n  - "https://a.example.com"\n  - "https://b.example.com"\n')

        assert load_node_urls(str(config)) == ["https://a.example.com", "https://b.example.com"]


class TestAuthenticateNode:
    """Tests for authenticate_node function."""

    @patch("molgenis_flwr_armadillo.authenticate.console")
    @patch("molgenis_flwr_armadillo.authenticate.MolgenisAuthClient")
    @patch(
        "molgenis_flwr_armadillo.authenticate.get_auth_info",
        return_value={"clientId": "cid", "issuerUri": "https://auth.example.com"},
    )
    def test_runs_device_flow_with_discovered_settings(self, mock_info, mock_client_cls, mock_console):
        from molgenis_flwr_armadillo.authenticate import authenticate_node

        mock_client_cls.return_value.device_flow_auth.return_value = {"access_token": "eyJ..."}

        assert authenticate_node("https://a.example.com") == "eyJ..."
        mock_info.assert_called_once_with("https://a.example.com")
        mock_client_cls.assert_called_once_with(
            auth_server="https://auth.example.com",
            client_id="cid",
            scopes="openid offline_access",
        )


class TestAuthenticate:
    """Tests for the authenticate orchestrator."""

    @patch("molgenis_flwr_armadillo.authenticate.print_summary")
    @patch("molgenis_flwr_armadillo.authenticate.save_tokens")
    @patch("molgenis_flwr_armadillo.authenticate.authenticate_node", side_effect=["tokA", "tokB"])
    @patch(
        "molgenis_flwr_armadillo.authenticate.load_node_urls",
        return_value=["https://a.example.com", "https://b.example.com"],
    )
    def test_keys_tokens_by_sanitized_url_and_saves(self, mock_urls, mock_node, mock_save, mock_summary):
        from molgenis_flwr_armadillo.authenticate import authenticate

        tokens = authenticate("flower-nodes.yaml")

        assert tokens == {"a-example-com": "tokA", "b-example-com": "tokB"}
        mock_save.assert_called_once_with(tokens)
        mock_summary.assert_called_once_with(["https://a.example.com", "https://b.example.com"])
