"""Tests for helper functions."""

import base64
import json
from unittest.mock import MagicMock, patch

import pytest

from molgenis_flwr_armadillo.helpers import (
    TOKENS_KEY,
    check_access,
    extract_tokens,
    get_node_token,
    get_node_url,
    list_projects,
    list_resources,
    sanitize_url,
)


def _blob(mapping: dict) -> str:
    """Encode a {sanitized-url: token} map the way armadillo-flwr-run does."""
    return base64.b64encode(json.dumps(mapping).encode()).decode()


class TestSanitizeUrl:
    """Tests for sanitize_url function."""

    @pytest.mark.parametrize(
        ("url", "key"),
        [
            ("https://armadillo-demo.molgenis.net", "armadillo-demo-molgenis-net"),
            ("http://armadillo-demo.molgenis.net", "armadillo-demo-molgenis-net"),
            ("HTTPS://Armadillo-DEMO.Molgenis.NET/", "armadillo-demo-molgenis-net"),
            ("http://localhost:8080", "localhost-8080"),
            ("https://host...name", "host-name"),
            ("https:///host/", "host"),
        ],
    )
    def test_converts_url_to_key(self, url, key):
        assert sanitize_url(url) == key

    @pytest.mark.parametrize(("url", "message"), [("", "must not be empty"), ("https://", "sanitizes to empty")])
    def test_rejects_urls_with_no_host(self, url, message):
        with pytest.raises(ValueError, match=message):
            sanitize_url(url)


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

    @patch("molgenis_flwr_armadillo.helpers.ARMADILLO_URL", "https://demo.example.com")
    def test_raises_on_undecodable_bundle(self):
        msg = MagicMock()
        msg.content = {"config": {TOKENS_KEY: "not-base64-json"}}

        with pytest.raises(RuntimeError, match="Failed to decode"):
            get_node_token(msg)

    @patch("molgenis_flwr_armadillo.helpers.ARMADILLO_URL", "https://demo.molgenis.net/")
    def test_url_trailing_slash_matches(self):
        """URL with trailing slash should find same token as without."""
        msg = MagicMock()
        msg.content = {
            "config": {TOKENS_KEY: _blob({"demo-molgenis-net": "the-token"})}
        }

        assert get_node_token(msg) == "the-token"


def _armadillo(projects, objects):
    """Fake _request returning Armadillo's real shapes: upper-case project names from
    /my/projects and "<project>/<path>" names from /storage/projects/{project}/objects."""
    def request(method, url, token, path):
        response = MagicMock()
        response.json.return_value = projects if path == "/my/projects" else objects
        return response
    return request


class TestListProjects:
    """Tests for list_projects function."""

    @patch("molgenis_flwr_armadillo.helpers._request")
    def test_returns_lower_case_project_names(self, mock_request):
        mock_request.side_effect = _armadillo(["PROJECT-A", "MYPROJECT"], [])

        assert list_projects("http://localhost:8080", "tok") == ["project-a", "myproject"]
        mock_request.assert_called_once_with("GET", "http://localhost:8080", "tok", "/my/projects")


class TestListResources:
    """Tests for list_resources function."""

    @patch("molgenis_flwr_armadillo.helpers._request")
    def test_returns_paths_within_the_project(self, mock_request):
        mock_request.side_effect = _armadillo([], ["proj/data/train.pt", "proj/test.pt"])

        assert list_resources("http://localhost:8080", "tok", "proj") == ["data/train.pt", "test.pt"]
        mock_request.assert_called_once_with(
            "GET", "http://localhost:8080", "tok", "/storage/projects/proj/objects"
        )


class TestCheckAccess:
    """Tests for check_access function, against Armadillo's real response shapes."""

    @patch("molgenis_flwr_armadillo.helpers._request")
    def test_passes_for_accessible_project_and_existing_resources(self, mock_request):
        mock_request.side_effect = _armadillo(["PROJ"], ["proj/data/train.pt", "proj/test.pt"])

        check_access("http://localhost:8080", "tok", "proj", ["data/train.pt"])

    @patch("molgenis_flwr_armadillo.helpers._request")
    def test_skips_resource_check_when_none_requested(self, mock_request):
        mock_request.side_effect = _armadillo(["PROJ"], [])

        check_access("http://localhost:8080", "tok", "proj")

        assert mock_request.call_count == 1

    @patch("molgenis_flwr_armadillo.helpers._request")
    def test_raises_when_project_not_accessible(self, mock_request):
        mock_request.side_effect = _armadillo(["OTHER"], [])

        with pytest.raises(RuntimeError, match="does not have access to project 'proj'"):
            check_access("http://localhost:8080", "tok", "proj")

    @patch("molgenis_flwr_armadillo.helpers._request")
    def test_raises_listing_missing_resources(self, mock_request):
        mock_request.side_effect = _armadillo(["PROJ"], ["proj/a.pt"])

        with pytest.raises(RuntimeError, match=r"\['b.pt'\]"):
            check_access("http://localhost:8080", "tok", "proj", ["a.pt", "b.pt"])
