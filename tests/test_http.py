"""Tests for the authenticated Armadillo request helper."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from molgenis_flwr_armadillo._http import _request


def _http_error(status: int) -> requests.exceptions.HTTPError:
    return requests.exceptions.HTTPError(response=MagicMock(status_code=status))


class TestRequest:
    """Tests for _request."""

    @patch("molgenis_flwr_armadillo._http.requests.request")
    def test_sends_bearer_token_and_default_timeout(self, mock_request):
        response = _request("GET", "http://localhost:8080", "tok", "/my/projects")

        assert response is mock_request.return_value
        mock_request.assert_called_once_with(
            "GET",
            "http://localhost:8080/my/projects",
            headers={"Authorization": "Bearer tok"},
            timeout=30,
        )

    @patch("molgenis_flwr_armadillo._http.requests.request")
    def test_forwards_timeout_and_extra_kwargs(self, mock_request):
        _request("POST", "http://localhost:8080", "tok", "/p", timeout=300, json={"a": 1})

        assert mock_request.call_args.kwargs["timeout"] == 300
        assert mock_request.call_args.kwargs["json"] == {"a": 1}

    @patch("molgenis_flwr_armadillo._http.requests.request")
    def test_strips_trailing_slash_from_url(self, mock_request):
        _request("GET", "http://localhost:8080/", "tok", "/p")

        assert mock_request.call_args[0][1] == "http://localhost:8080/p"

    @pytest.mark.parametrize(
        ("status", "message"),
        [
            (401, "Authentication failed"),
            (403, "Access denied"),
            (404, "Not found"),
            (500, "HTTP 500"),
        ],
    )
    @patch("molgenis_flwr_armadillo._http.requests.request")
    def test_maps_http_errors(self, mock_request, status, message):
        mock_request.return_value.raise_for_status.side_effect = _http_error(status)

        with pytest.raises(RuntimeError, match=message):
            _request("GET", "http://localhost:8080", "tok", "/p")

    @patch("molgenis_flwr_armadillo._http.requests.request")
    def test_maps_connection_error(self, mock_request):
        mock_request.side_effect = requests.exceptions.ConnectionError()

        with pytest.raises(RuntimeError, match="Could not connect"):
            _request("GET", "http://localhost:8080", "tok", "/p")

    @patch("molgenis_flwr_armadillo._http.requests.request")
    def test_maps_timeout(self, mock_request):
        mock_request.side_effect = requests.exceptions.ReadTimeout()

        with pytest.raises(RuntimeError, match="within 30s"):
            _request("GET", "http://localhost:8080", "tok", "/p")
