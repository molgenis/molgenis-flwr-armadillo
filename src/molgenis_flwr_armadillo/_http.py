"""Authenticated HTTP requests to Armadillo."""

import requests

# Same wording as DSMolgenisArmadillo's .handle_request_error, so researchers see
# one set of messages from R and Python; the server's own message is added for the
# statuses where DSMolgenisArmadillo shows it, and for anything unmapped.
ERROR_PREFIXES = {
    400: "Bad request",
    401: "Unauthorized",
    403: "Access denied",
    404: "Not found",
    500: "Internal server error",
    503: "Service unavailable",
}
WITH_SERVER_MESSAGE = {400, 500, 503}


def _auth_headers(token: str) -> dict:
    """Build authorization headers."""
    return {"Authorization": f"Bearer {token}"}


def server_message(response: requests.Response) -> str:
    """Return Armadillo's JSON ``message`` for a failed response, else its raw body."""
    try:
        return response.json().get("message") or response.text
    except ValueError:
        return response.text


def describe_http_error(response: requests.Response, endpoint: str) -> str:
    """Build the error text for a failed Armadillo response."""
    status = response.status_code
    text = f"{ERROR_PREFIXES.get(status, f'HTTP {status}')} ({endpoint})"
    if status in WITH_SERVER_MESSAGE or status not in ERROR_PREFIXES:
        text += f": {server_message(response)}"
    if status == 401:
        text += ". Re-run armadillo-flwr-authenticate to get a new token."
    return text


def _request(method: str, url: str, token: str, path: str, timeout: float = 30, **kwargs):
    """Make an authenticated request to Armadillo with error handling."""
    endpoint = f"{url.rstrip('/')}{path}"
    try:
        response = requests.request(
            method, endpoint, headers=_auth_headers(token), timeout=timeout, **kwargs
        )
    except requests.exceptions.Timeout as e:
        raise RuntimeError(
            f"No response from Armadillo at {endpoint} within {timeout}s."
        ) from e
    except requests.exceptions.ConnectionError as e:
        raise RuntimeError(
            f"Could not connect to Armadillo at {endpoint}. "
            f"Check that the server is running and the URL is correct."
        ) from e
    if not response.ok:
        raise RuntimeError(describe_http_error(response, endpoint))
    return response
