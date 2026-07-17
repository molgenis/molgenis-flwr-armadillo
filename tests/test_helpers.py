"""Tests for helper functions."""

import base64
import json
import pytest
from unittest.mock import MagicMock, patch

from molgenis_flwr_armadillo.helpers import (
    TOKENS_KEY,
    extract_tokens,
    get_node_token,
    get_node_url,
    load_data,
    sanitize_url,
)


def _blob(mapping: dict) -> str:
    """Encode a {sanitized-url: token} map the way armadillo-flwr-run does."""
    return base64.b64encode(json.dumps(mapping).encode()).decode()


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

    def test_extracts_token_bundle(self):
        """Should return the single armadillo-tokens run-config entry."""
        blob = _blob({"armadillo-demo-molgenis-net": "abc123"})
        context = MagicMock()
        context.run_config = {
            "learning-rate": 0.1,
            "batch-size": 32,
            TOKENS_KEY: blob,
        }

        assert extract_tokens(context) == {TOKENS_KEY: blob}

    def test_returns_empty_dict_when_no_tokens(self):
        context = MagicMock()
        context.run_config = {"learning-rate": 0.1}

        assert extract_tokens(context) == {}

    def test_handles_empty_run_config(self):
        context = MagicMock()
        context.run_config = {}

        assert extract_tokens(context) == {}

    def test_ignores_empty_bundle(self):
        context = MagicMock()
        context.run_config = {TOKENS_KEY: ""}

        assert extract_tokens(context) == {}


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
                TOKENS_KEY: _blob(
                    {
                        "armadillo-demo-molgenis-net": "demo-token-value",
                        "localhost-8080": "localhost-token-value",
                    }
                )
            }
        }

        assert get_node_token(msg) == "demo-token-value"

    @patch("molgenis_flwr_armadillo.helpers.ARMADILLO_URL", "https://unknown.example.com")
    def test_raises_when_token_not_found(self):
        msg = MagicMock()
        msg.content = {
            "config": {
                TOKENS_KEY: _blob({"armadillo-demo-molgenis-net": "demo-token-value"})
            }
        }

        with pytest.raises(RuntimeError, match="No token found"):
            get_node_token(msg)

    @patch("molgenis_flwr_armadillo.helpers.ARMADILLO_URL", "")
    def test_raises_when_armadillo_url_not_set(self):
        msg = MagicMock()
        msg.content = {"config": {TOKENS_KEY: _blob({"demo": "value"})}}

        with pytest.raises(RuntimeError, match="ARMADILLO_URL"):
            get_node_token(msg)

    @patch("molgenis_flwr_armadillo.helpers.ARMADILLO_URL", "https://demo.example.com")
    def test_raises_when_bundle_missing(self):
        msg = MagicMock()
        msg.content = {}

        with pytest.raises(RuntimeError, match=TOKENS_KEY):
            get_node_token(msg)

    @patch("molgenis_flwr_armadillo.helpers.ARMADILLO_URL", "https://demo.molgenis.net/")
    def test_url_trailing_slash_matches(self):
        """URL with trailing slash should find same token as without."""
        msg = MagicMock()
        msg.content = {
            "config": {TOKENS_KEY: _blob({"demo-molgenis-net": "the-token"})}
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
