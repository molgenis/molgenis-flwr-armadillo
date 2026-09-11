"""Tests for the authenticated Armadillo request helper."""

import json
from unittest.mock import patch

import pytest
import requests

from molgenis_flwr_armadillo._http import _request

ENDPOINT = "http://localhost:8080/p"


def _response(status: int, body: dict | str = "") -> requests.Response:
    """A real requests.Response with the given status and JSON (dict) or text body."""
    response = requests.Response()
    response.status_code = status
    response._content = (json.dumps(body) if isinstance(body, dict) else body).encode()
    return response


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
        ("status", "body", "message"),
        [
            (400, {"message": "fabHash must be 64 hex chars"}, f"Bad request ({ENDPOINT}): fabHash must be 64 hex chars"),
            (401, {}, f"Unauthorized ({ENDPOINT}). Re-run armadillo-flwr-authenticate to get a new token."),
            (403, {"message": "ignored"}, f"Access denied ({ENDPOINT})"),
            (404, {"message": "ignored"}, f"Not found ({ENDPOINT})"),
            (500, {"message": "boom"}, f"Internal server error ({ENDPOINT}): boom"),
            (503, "maintenance", f"Service unavailable ({ENDPOINT}): maintenance"),
            (409, {"message": "already exists"}, f"HTTP 409 ({ENDPOINT}): already exists"),
        ],
    )
    @patch("molgenis_flwr_armadillo._http.requests.request")
    def test_maps_http_errors_like_dsmolgenisarmadillo(self, mock_request, status, body, message):
        mock_request.return_value = _response(status, body)

        with pytest.raises(RuntimeError) as exc_info:
            _request("GET", "http://localhost:8080", "tok", "/p")

        assert str(exc_info.value) == message

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
