"""Tests for authentication functions."""

import stat
from unittest.mock import MagicMock, patch

import pytest

import molgenis_flwr_armadillo.authenticate as auth_mod


@pytest.fixture
def token_file(tmp_path, monkeypatch):
    """Point TOKEN_FILE at a fresh path under tmp_path."""
    path = tmp_path / ".molgenis-flwr" / "tokens.json"
    monkeypatch.setattr(auth_mod, "TOKEN_FILE", path)
    return path


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


class TestSaveAndLoadTokens:
    """Tests for save_tokens and load_tokens functions."""

    def test_save_and_load_roundtrip(self, token_file):
        tokens = {"a-example-com": "tokA", "localhost-8080": "tokB"}

        auth_mod.save_tokens(tokens)

        assert auth_mod.load_tokens() == tokens

    def test_load_raises_when_file_missing(self, token_file):
        with pytest.raises(FileNotFoundError, match="No tokens found"):
            auth_mod.load_tokens()

    def test_save_overwrites_existing(self, token_file):
        auth_mod.save_tokens({"a-example-com": "old"})
        auth_mod.save_tokens({"b-example-com": "new"})

        assert auth_mod.load_tokens() == {"b-example-com": "new"}

    def test_token_file_is_private(self, token_file):
        """Should create the file 0600, and restrict a pre-existing looser one."""
        token_file.parent.mkdir()
        token_file.write_text("{}")
        token_file.chmod(0o644)

        auth_mod.save_tokens({"a-example-com": "tokA"})

        assert stat.S_IMODE(token_file.stat().st_mode) == 0o600

    def test_creates_private_directory(self, token_file):
        auth_mod.save_tokens({"a-example-com": "tokA"})

        assert stat.S_IMODE(token_file.parent.stat().st_mode) == 0o700


class TestLoadNodeUrls:
    """Tests for load_node_urls function."""

    def test_reads_urls_from_yaml(self, tmp_path):
        from molgenis_flwr_armadillo.authenticate import load_node_urls

        config = tmp_path / "flower-nodes.yaml"
        config.write_text('urls:\n  - "https://a.example.com"\n  - "https://b.example.com"\n')

        assert load_node_urls(str(config)) == ["https://a.example.com", "https://b.example.com"]

    @pytest.mark.parametrize("content", ["", "nodes:\n  - x\n"])
    def test_raises_when_urls_missing(self, tmp_path, content):
        config = tmp_path / "flower-nodes.yaml"
        config.write_text(content)

        with pytest.raises(ValueError, match="has no 'urls' list"):
            auth_mod.load_node_urls(str(config))


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


class TestMain:
    """Tests for the armadillo-flwr-authenticate entry point."""

    def test_exits_cleanly_when_config_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr("sys.argv", ["armadillo-flwr-authenticate", "--config", str(tmp_path / "none.yaml")])

        with pytest.raises(SystemExit) as exc_info:
            auth_mod.main()

        assert exc_info.value.code == 1
