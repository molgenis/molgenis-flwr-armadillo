"""Tests for helper functions."""

import pytest
from unittest.mock import MagicMock, patch

from molgenis_flwr_armadillo.helpers import (
    extract_tokens,
    get_node_token,
    get_node_url,
    load_data,
    sanitize_url,
)


class TestSanitizeUrl:
    """Tests for sanitize_url function."""

    def test_strips_https_scheme(self):
        assert sanitize_url("https://armadillo-demo.molgenis.net") == "armadillo-demo-molgenis-net"

    def test_strips_http_scheme(self):
        assert sanitize_url("http://localhost:8080") == "localhost-8080"

    def test_strips_trailing_slash(self):
        assert sanitize_url("https://armadillo-demo.molgenis.net/") == "armadillo-demo-molgenis-net"

    def test_lowercases(self):
        assert sanitize_url("https://Armadillo-DEMO.Molgenis.NET") == "armadillo-demo-molgenis-net"

    def test_replaces_dots_with_hyphens(self):
        assert sanitize_url("https://armadillo.dev.molgenis.org") == "armadillo-dev-molgenis-org"

    def test_collapses_multiple_special_chars(self):
        assert sanitize_url("https://host...name") == "host-name"

    def test_strips_leading_trailing_hyphens(self):
        assert sanitize_url("https:///host/") == "host"

    def test_raises_on_empty_string(self):
        with pytest.raises(ValueError, match="must not be empty"):
            sanitize_url("")

    def test_raises_on_scheme_only(self):
        with pytest.raises(ValueError, match="sanitizes to empty"):
            sanitize_url("https://")

    def test_preserves_port(self):
        assert sanitize_url("https://localhost:9090") == "localhost-9090"

    def test_consistent_results(self):
        """Same URL with different formatting produces same key."""
        assert sanitize_url("https://demo.molgenis.net") == sanitize_url("https://demo.molgenis.net/")
        assert sanitize_url("http://demo.molgenis.net") == sanitize_url("https://demo.molgenis.net")
        assert sanitize_url("HTTPS://Demo.Molgenis.NET") == sanitize_url("https://demo.molgenis.net")


class TestExtractTokens:
    """Tests for extract_tokens function."""

    def test_extracts_token_keys(self):
        """Should extract only keys starting with 'token-'."""
        context = MagicMock()
        context.run_config = {
            "learning-rate": 0.1,
            "batch-size": 32,
            "token-armadillo-demo-molgenis-net": "abc123",
            "token-localhost-8080": "xyz789",
        }

        result = extract_tokens(context)

        assert result == {
            "token-armadillo-demo-molgenis-net": "abc123",
            "token-localhost-8080": "xyz789",
        }

    def test_does_not_extract_url_keys(self):
        """Should not extract url- keys (URLs come from node_config now)."""
        context = MagicMock()
        context.run_config = {
            "token-armadillo-demo-molgenis-net": "abc123",
            "url-demo": "https://armadillo-demo.molgenis.net",
        }

        result = extract_tokens(context)

        assert result == {"token-armadillo-demo-molgenis-net": "abc123"}

    def test_returns_empty_dict_when_no_tokens(self):
        context = MagicMock()
        context.run_config = {"learning-rate": 0.1}

        assert extract_tokens(context) == {}

    def test_handles_empty_run_config(self):
        context = MagicMock()
        context.run_config = {}

        assert extract_tokens(context) == {}

    def test_does_not_extract_partial_matches(self):
        context = MagicMock()
        context.run_config = {
            "my-token": "should-not-match",
            "tokenizer": "should-not-match",
            "token-demo": "should-match",
        }

        assert extract_tokens(context) == {"token-demo": "should-match"}


class TestGetNodeUrl:
    """Tests for get_node_url function."""

    @patch("molgenis_flwr_armadillo.helpers.ARMADILLO_URL", "https://armadillo-demo.molgenis.net")
    def test_reads_url_from_env(self):
        assert get_node_url() == "https://armadillo-demo.molgenis.net"

    @patch("molgenis_flwr_armadillo.helpers.ARMADILLO_URL", "")
    def test_raises_when_env_not_set(self):
        with pytest.raises(RuntimeError, match="ARMADILLO_URL"):
            get_node_url()


class TestGetNodeToken:
    """Tests for get_node_token function."""

    @patch("molgenis_flwr_armadillo.helpers.ARMADILLO_URL", "https://armadillo-demo.molgenis.net")
    def test_extracts_correct_token_by_url(self):
        msg = MagicMock()
        msg.content = {
            "config": {
                "token-armadillo-demo-molgenis-net": "demo-token-value",
                "token-localhost-8080": "localhost-token-value",
            }
        }

        assert get_node_token(msg) == "demo-token-value"

    @patch("molgenis_flwr_armadillo.helpers.ARMADILLO_URL", "https://unknown.example.com")
    def test_raises_when_token_not_found(self):
        msg = MagicMock()
        msg.content = {
            "config": {
                "token-armadillo-demo-molgenis-net": "demo-token-value",
            }
        }

        with pytest.raises(RuntimeError, match="No token found"):
            get_node_token(msg)

    @patch("molgenis_flwr_armadillo.helpers.ARMADILLO_URL", "")
    def test_raises_when_armadillo_url_not_set(self):
        msg = MagicMock()
        msg.content = {"config": {"token-demo": "value"}}

        with pytest.raises(RuntimeError, match="ARMADILLO_URL"):
            get_node_token(msg)

    @patch("molgenis_flwr_armadillo.helpers.ARMADILLO_URL", "https://demo.example.com")
    def test_handles_missing_config_in_message(self):
        msg = MagicMock()
        msg.content = {}

        with pytest.raises(RuntimeError, match="No token found"):
            get_node_token(msg)

    @patch("molgenis_flwr_armadillo.helpers.ARMADILLO_URL", "https://demo.molgenis.net/")
    def test_url_trailing_slash_matches(self):
        """URL with trailing slash should find same token as without."""
        msg = MagicMock()
        msg.content = {
            "config": {
                "token-demo-molgenis-net": "the-token",
            }
        }

        assert get_node_token(msg) == "the-token"


class TestLoadData:
    """Tests for load_data function."""

    @patch("molgenis_flwr_armadillo.helpers.CONTAINER_NAME", "flower-client-1")
    @patch("molgenis_flwr_armadillo.helpers.requests.request")
    def test_posts_to_armadillo(self, mock_request, tmp_path):
        """Should POST to /flower/push-data with correct payload."""
        mock_request.return_value.status_code = 204
        mock_request.return_value.raise_for_status = MagicMock()

        data_dir = tmp_path / "armadillo_data"
        data_dir.mkdir()
        filepath = data_dir / "myproject_train.parquet"
        filepath.write_bytes(b"test data")

        with patch("molgenis_flwr_armadillo.helpers.DATA_DIR", data_dir):
            load_data("https://armadillo.example.com", "my-token", "myproject", "train.parquet")

        mock_request.assert_called_once_with(
            "POST",
            "https://armadillo.example.com/flower/push-data",
            headers={"Authorization": "Bearer my-token"},
            json={
                "project": "myproject",
                "resource": "train.parquet",
                "containerName": "flower-client-1",
            },
        )

    @patch("molgenis_flwr_armadillo.helpers.CONTAINER_NAME", "flower-client-1")
    @patch("molgenis_flwr_armadillo.helpers.requests.request")
    def test_reads_and_deletes_file(self, mock_request, tmp_path):
        """Should read file into bytes and delete it."""
        mock_request.return_value.raise_for_status = MagicMock()

        data_dir = tmp_path / "armadillo_data"
        data_dir.mkdir()
        filepath = data_dir / "proj_data_train"
        filepath.write_bytes(b"raw file content")

        with patch("molgenis_flwr_armadillo.helpers.DATA_DIR", data_dir):
            result = load_data("http://localhost:8080", "token", "proj", "data/train")

        assert result == b"raw file content"
        assert not filepath.exists()

    @patch("molgenis_flwr_armadillo.helpers.CONTAINER_NAME", "flower-client-1")
    @patch("molgenis_flwr_armadillo.helpers.requests.request")
    def test_strips_trailing_slash_from_url(self, mock_request, tmp_path):
        """Should strip trailing slash from URL."""
        mock_request.return_value.raise_for_status = MagicMock()

        data_dir = tmp_path / "armadillo_data"
        data_dir.mkdir()
        (data_dir / "proj_file").write_bytes(b"data")

        with patch("molgenis_flwr_armadillo.helpers.DATA_DIR", data_dir):
            load_data("http://localhost:8080/", "token", "proj", "file")

        assert mock_request.call_args[0][1] == "http://localhost:8080/flower/push-data"

    @patch("molgenis_flwr_armadillo.helpers.CONTAINER_NAME", "")
    def test_raises_when_container_name_not_set(self):
        """Should raise RuntimeError when ARMADILLO_CONTAINER_NAME is not set."""
        with pytest.raises(RuntimeError, match="ARMADILLO_CONTAINER_NAME"):
            load_data("http://localhost:8080", "token", "proj", "file")
