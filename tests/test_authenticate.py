"""Tests for authentication functions."""

import json
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
        mock_get.assert_called_once_with("https://armadillo.example.com/actuator/info")

    @patch("requests.get")
    def test_strips_trailing_slash(self, mock_get):
        """Should strip trailing slash from URL."""
        from molgenis_flwr_armadillo.authenticate import get_auth_info

        mock_response = MagicMock()
        mock_response.json.return_value = {"auth": {"clientId": "x", "issuerUri": "y"}}
        mock_get.return_value = mock_response

        get_auth_info("https://armadillo.example.com/")

        mock_get.assert_called_once_with("https://armadillo.example.com/actuator/info")

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
        from molgenis_flwr_armadillo.authenticate import save_tokens, load_tokens

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
        from molgenis_flwr_armadillo.authenticate import save_tokens, load_tokens

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
        from molgenis_flwr_armadillo.authenticate import save_tokens, load_tokens

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
