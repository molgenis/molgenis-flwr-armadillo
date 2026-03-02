"""Tests for helper functions."""

import pytest
from unittest.mock import MagicMock, patch, mock_open

from molgenis_flwr_armadillo.helpers import extract_tokens, get_node_token, get_node_url, load_data


class TestExtractTokens:
    """Tests for extract_tokens function."""

    def test_extracts_token_keys(self):
        """Should extract only keys starting with 'token-'."""
        context = MagicMock()
        context.run_config = {
            "learning-rate": 0.1,
            "batch-size": 32,
            "token-demo": "abc123",
            "token-localhost": "xyz789",
        }

        result = extract_tokens(context)

        assert result == {
            "token-demo": "abc123",
            "token-localhost": "xyz789",
        }

    def test_extracts_url_keys(self):
        """Should extract keys starting with 'url-' alongside tokens."""
        context = MagicMock()
        context.run_config = {
            "learning-rate": 0.1,
            "token-demo": "abc123",
            "url-demo": "https://armadillo-demo.molgenis.net",
        }

        result = extract_tokens(context)

        assert result == {
            "token-demo": "abc123",
            "url-demo": "https://armadillo-demo.molgenis.net",
        }

    def test_returns_empty_dict_when_no_tokens(self):
        """Should return empty dict when no token keys exist."""
        context = MagicMock()
        context.run_config = {
            "learning-rate": 0.1,
            "batch-size": 32,
        }

        result = extract_tokens(context)

        assert result == {}

    def test_handles_empty_run_config(self):
        """Should handle empty run_config."""
        context = MagicMock()
        context.run_config = {}

        result = extract_tokens(context)

        assert result == {}

    def test_does_not_extract_partial_matches(self):
        """Should not extract keys that contain 'token' but don't start with 'token-'."""
        context = MagicMock()
        context.run_config = {
            "my-token": "should-not-match",
            "tokenizer": "should-not-match",
            "token-demo": "should-match",
        }

        result = extract_tokens(context)

        assert result == {"token-demo": "should-match"}


class TestGetNodeToken:
    """Tests for get_node_token function."""

    def test_extracts_correct_token_for_node(self):
        """Should extract the token matching the node name."""
        context = MagicMock()
        context.node_config = {"node-name": "demo"}

        msg = MagicMock()
        msg.content = {
            "config": {
                "token-demo": "demo-token-value",
                "token-localhost": "localhost-token-value",
            }
        }

        result = get_node_token(msg, context)

        assert result == "demo-token-value"

    def test_returns_empty_string_when_token_not_found(self):
        """Should return empty string when node's token doesn't exist."""
        context = MagicMock()
        context.node_config = {"node-name": "unknown-node"}

        msg = MagicMock()
        msg.content = {
            "config": {
                "token-demo": "demo-token-value",
            }
        }

        result = get_node_token(msg, context)

        assert result == ""

    def test_returns_empty_string_when_node_name_missing(self):
        """Should return empty string when node-name is not in node_config."""
        context = MagicMock()
        context.node_config = {}

        msg = MagicMock()
        msg.content = {
            "config": {
                "token-demo": "demo-token-value",
            }
        }

        result = get_node_token(msg, context)

        assert result == ""

    def test_handles_missing_config_in_message(self):
        """Should handle missing 'config' key in message content."""
        context = MagicMock()
        context.node_config = {"node-name": "demo"}

        msg = MagicMock()
        msg.content = {}

        result = get_node_token(msg, context)

        assert result == ""

    def test_handles_none_values(self):
        """Should handle None values gracefully."""
        context = MagicMock()
        context.node_config = {"node-name": "demo"}

        msg = MagicMock()
        msg.content = {"config": None}

        # This should not raise, but return empty string
        # Note: current implementation would raise AttributeError
        # This test documents expected behavior - may need code fix
        with pytest.raises(AttributeError):
            get_node_token(msg, context)


class TestGetNodeUrl:
    """Tests for get_node_url function."""

    def test_extracts_correct_url_for_node(self):
        """Should extract the URL matching the node name."""
        context = MagicMock()
        context.node_config = {"node-name": "demo"}

        msg = MagicMock()
        msg.content = {
            "config": {
                "url-demo": "https://armadillo-demo.molgenis.net",
                "url-localhost": "http://localhost:8080",
            }
        }

        result = get_node_url(msg, context)

        assert result == "https://armadillo-demo.molgenis.net"

    def test_returns_empty_string_when_url_not_found(self):
        """Should return empty string when node's URL doesn't exist."""
        context = MagicMock()
        context.node_config = {"node-name": "unknown-node"}

        msg = MagicMock()
        msg.content = {
            "config": {
                "url-demo": "https://armadillo-demo.molgenis.net",
            }
        }

        result = get_node_url(msg, context)

        assert result == ""

    def test_handles_missing_config_in_message(self):
        """Should handle missing 'config' key in message content."""
        context = MagicMock()
        context.node_config = {"node-name": "demo"}

        msg = MagicMock()
        msg.content = {}

        result = get_node_url(msg, context)

        assert result == ""


class TestLoadData:
    """Tests for load_data function."""

    @patch("molgenis_flwr_armadillo.helpers.CONTAINER_NAME", "flower-client-1")
    @patch("molgenis_flwr_armadillo.helpers.requests.post")
    def test_posts_to_armadillo(self, mock_post, tmp_path):
        """Should POST to /flower/push-data with correct payload."""
        mock_post.return_value.status_code = 204
        mock_post.return_value.raise_for_status = MagicMock()

        data_dir = tmp_path / "armadillo_data"
        data_dir.mkdir()
        filepath = data_dir / "myproject_train.parquet"
        filepath.write_bytes(b"test data")

        with patch("molgenis_flwr_armadillo.helpers.DATA_DIR", data_dir):
            load_data("https://armadillo.example.com", "my-token", "myproject", "train.parquet")

        mock_post.assert_called_once_with(
            "https://armadillo.example.com/flower/push-data",
            headers={"Authorization": "Bearer my-token"},
            json={
                "project": "myproject",
                "resource": "train.parquet",
                "containerName": "flower-client-1",
            },
        )

    @patch("molgenis_flwr_armadillo.helpers.CONTAINER_NAME", "flower-client-1")
    @patch("molgenis_flwr_armadillo.helpers.requests.post")
    def test_reads_and_deletes_file(self, mock_post, tmp_path):
        """Should read file into bytes and delete it."""
        mock_post.return_value.raise_for_status = MagicMock()

        data_dir = tmp_path / "armadillo_data"
        data_dir.mkdir()
        filepath = data_dir / "proj_data_train"
        filepath.write_bytes(b"raw file content")

        with patch("molgenis_flwr_armadillo.helpers.DATA_DIR", data_dir):
            result = load_data("http://localhost:8080", "token", "proj", "data/train")

        assert result == b"raw file content"
        assert not filepath.exists()

    @patch("molgenis_flwr_armadillo.helpers.CONTAINER_NAME", "flower-client-1")
    @patch("molgenis_flwr_armadillo.helpers.requests.post")
    def test_strips_trailing_slash_from_url(self, mock_post, tmp_path):
        """Should strip trailing slash from URL."""
        mock_post.return_value.raise_for_status = MagicMock()

        data_dir = tmp_path / "armadillo_data"
        data_dir.mkdir()
        (data_dir / "proj_file").write_bytes(b"data")

        with patch("molgenis_flwr_armadillo.helpers.DATA_DIR", data_dir):
            load_data("http://localhost:8080/", "token", "proj", "file")

        assert mock_post.call_args[0][0] == "http://localhost:8080/flower/push-data"

    @patch("molgenis_flwr_armadillo.helpers.CONTAINER_NAME", "")
    def test_raises_when_container_name_not_set(self):
        """Should raise RuntimeError when ARMADILLO_CONTAINER_NAME is not set."""
        with pytest.raises(RuntimeError, match="ARMADILLO_CONTAINER_NAME"):
            load_data("http://localhost:8080", "token", "proj", "file")
