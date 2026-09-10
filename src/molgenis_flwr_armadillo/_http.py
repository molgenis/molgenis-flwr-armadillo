"""Authenticated HTTP requests to Armadillo."""

import requests


def _auth_headers(token: str) -> dict:
    """Build authorization headers."""
    return {"Authorization": f"Bearer {token}"}


def _request(method: str, url: str, token: str, path: str, timeout: float = 30, **kwargs):
    """Make an authenticated request to Armadillo with error handling."""
    endpoint = f"{url.rstrip('/')}{path}"
    try:
        response = requests.request(
            method, endpoint, headers=_auth_headers(token), timeout=timeout, **kwargs
        )
        response.raise_for_status()
        return response
    except requests.exceptions.Timeout as e:
        raise RuntimeError(
            f"No response from Armadillo at {endpoint} within {timeout}s."
        ) from e
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else "unknown"
        if status == 401:
            raise RuntimeError(
                f"Authentication failed (HTTP 401) from {endpoint}. "
                f"The OIDC token may have expired. "
                f"Re-run armadillo-flwr-authenticate to get a new token."
            ) from e
        elif status == 403:
            raise RuntimeError(
                f"Access denied (HTTP 403) from {endpoint}. "
                f"The authenticated user does not have permission to access "
                f"this resource. Check project permissions in Armadillo."
            ) from e
        elif status == 404:
            raise RuntimeError(
                f"Not found (HTTP 404) from {endpoint}. "
                f"The project or resource may not exist."
            ) from e
        else:
            raise RuntimeError(f"HTTP {status} from {endpoint}: {e}") from e
    except requests.exceptions.ConnectionError as e:
        raise RuntimeError(
            f"Could not connect to Armadillo at {endpoint}. "
            f"Check that the server is running and the URL is correct."
        ) from e
