"""Tests for the app review and approval CLIs."""

import sys
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from molgenis_flwr_armadillo.approve_app import (
    add_to_whitelist,
    approve_main,
    armadillo_auth,
    build_whitelist_entry,
    pull_fab,
    review_main,
)

ENTRY = {"fab_id": "publisher/app", "fab_version": "1.0.0", "fab_hash": "a" * 64}


class TestBuildWhitelistEntry:
    """Tests for build_whitelist_entry."""

    @patch("molgenis_flwr_armadillo.approve_app.get_sha256_hash", return_value="abc123")
    @patch(
        "molgenis_flwr_armadillo.approve_app.get_fab_metadata",
        return_value=("publisher/app", "1.0.0"),
    )
    def test_combines_metadata_and_hash_from_same_file(self, mock_metadata, mock_hash):
        fab_path = Path("some.fab")

        assert build_whitelist_entry(fab_path) == {
            "fab_id": "publisher/app",
            "fab_version": "1.0.0",
            "fab_hash": "abc123",
        }
        mock_metadata.assert_called_once_with(fab_path)
        mock_hash.assert_called_once_with(fab_path)


class TestPullFab:
    """Tests for pull_fab."""

    @patch("molgenis_flwr_armadillo.approve_app.console")
    @patch("molgenis_flwr_armadillo.approve_app.requests.get")
    @patch(
        "molgenis_flwr_armadillo.approve_app.request_download_link",
        return_value=("https://cdn.example/app.fab", None, "built for flwr 1.32"),
    )
    @patch(
        "molgenis_flwr_armadillo.approve_app.parse_app_spec",
        return_value=("@publisher/app", "1.0.0"),
    )
    def test_downloads_and_saves_fab(self, mock_parse, mock_link, mock_get, mock_console, tmp_path):
        mock_get.return_value.content = b"fab bytes"

        fab_path = pull_fab("@publisher/app==1.0.0", tmp_path / "reviews")

        assert fab_path == tmp_path / "reviews" / "publisher-app.fab"
        assert fab_path.read_bytes() == b"fab bytes"
        mock_link.assert_called_once()
        assert mock_link.call_args[0][:2] == ("@publisher/app", "1.0.0")
        mock_get.assert_called_once_with("https://cdn.example/app.fab", timeout=60)
        assert "built for flwr 1.32" in str(mock_console.print.call_args)


class TestArmadilloAuth:
    """Tests for armadillo_auth."""

    @patch("molgenis_flwr_armadillo.approve_app.getpass.getpass", return_value="secret")
    def test_basic_auth_when_user_given(self, mock_getpass):
        assert armadillo_auth("http://localhost:8080", "admin") == {"auth": ("admin", "secret")}

    @patch(
        "molgenis_flwr_armadillo.approve_app.load_tokens",
        return_value={"localhost-8080": "tok"},
    )
    def test_bearer_token_looked_up_by_sanitized_url(self, mock_tokens):
        assert armadillo_auth("http://localhost:8080/", None) == {
            "headers": {"Authorization": "Bearer tok"}
        }

    @patch("molgenis_flwr_armadillo.approve_app.load_tokens", return_value={"other": "tok"})
    def test_raises_when_no_token_for_server(self, mock_tokens):
        with pytest.raises(RuntimeError, match="No token for http://localhost:8080"):
            armadillo_auth("http://localhost:8080", None)

    @patch(
        "molgenis_flwr_armadillo.approve_app.load_tokens",
        side_effect=FileNotFoundError("No tokens found"),
    )
    def test_raises_when_no_token_file(self, mock_tokens):
        with pytest.raises(RuntimeError, match="armadillo-flwr-authenticate"):
            armadillo_auth("http://localhost:8080", None)


class TestAddToWhitelist:
    """Tests for add_to_whitelist."""

    @patch("molgenis_flwr_armadillo.approve_app.requests.post")
    def test_posts_entry_to_container_endpoint(self, mock_post):
        mock_post.return_value = MagicMock(status_code=204, ok=True)

        add_to_whitelist(
            "http://localhost:8080/", "clientapp-1", ENTRY, {"headers": {"Authorization": "Bearer t"}}
        )

        mock_post.assert_called_once_with(
            "http://localhost:8080/containers/clientapp-1/fab-whitelist",
            json={"fabId": "publisher/app", "fabVersion": "1.0.0", "fabHash": "a" * 64},
            timeout=30,
            headers={"Authorization": "Bearer t"},
        )

    @pytest.mark.parametrize(
        ("status", "message"),
        [
            (401, r"Unauthorized \(.*/fab-whitelist\)\. Re-run armadillo-flwr-authenticate"),
            (403, r"Access denied \(.*/fab-whitelist\)"),
            (404, r"Not found \(.*/containers/clientapp-1/fab-whitelist\)"),
            (400, r"Bad request \(.*/fab-whitelist\): fabHash must be 64 hex chars"),
        ],
    )
    @patch("molgenis_flwr_armadillo.approve_app.requests.post")
    def test_maps_server_errors(self, mock_post, status, message):
        response = requests.Response()
        response.status_code = status
        response._content = b'{"message": "fabHash must be 64 hex chars"}'
        mock_post.return_value = response

        with pytest.raises(RuntimeError, match=message):
            add_to_whitelist("http://localhost:8080", "clientapp-1", ENTRY, {"auth": ("a", "b")})


TARGET = "molgenis_flwr_armadillo.approve_app"
APPROVE_ARGS = ["--armadillo", "http://localhost:8080", "--container", "c1"]


def run_cli(entry_point, argv):
    """Run a CLI entry point with argv; return its exit code (0 if it returned)."""
    with patch.object(sys, "argv", ["prog", *argv]):
        try:
            entry_point()
        except SystemExit as e:
            return e.code
    return 0


class TestReviewApp:
    """Tests for armadillo-flwr-review-app."""

    @patch(f"{TARGET}.console")
    @patch(f"{TARGET}.unpack_for_review", return_value=Path("/reviews/app"))
    @patch(f"{TARGET}.build_whitelist_entry", return_value=ENTRY)
    @patch(f"{TARGET}.pull_fab", return_value=Path("/reviews/publisher-app.fab"))
    def test_downloads_unpacks_and_prints_the_approve_command(self, mock_pull, mock_entry, mock_unpack, mock_console):
        assert run_cli(review_main, ["@publisher/app"]) == 0

        mock_pull.assert_called_once()
        mock_unpack.assert_called_once_with(Path("/reviews/publisher-app.fab"), mock_pull.call_args[0][1])
        printed = " ".join(str(c.args[0]) for c in mock_console.print.call_args_list if c.args)
        assert "armadillo-flwr-approve-app /reviews/publisher-app.fab" in printed

    @patch(f"{TARGET}.console")
    @patch(f"{TARGET}.pull_fab", side_effect=requests.ConnectionError("boom"))
    def test_download_failure_exits_nonzero(self, mock_pull, mock_console):
        assert run_cli(review_main, ["@publisher/app"]) == 1

    @pytest.mark.parametrize("make_fab", ["not a zip", "zip without pyproject"])
    @patch(f"{TARGET}.console")
    def test_invalid_local_fab_exits_without_traceback(self, mock_console, tmp_path, make_fab):
        fab = tmp_path / "app.fab"
        if make_fab == "not a zip":
            fab.write_bytes(b"not a zip")
        else:
            with zipfile.ZipFile(fab, "w") as archive:
                archive.writestr("readme.txt", "x")

        assert run_cli(review_main, [str(fab)]) == 1


class TestApproveApp:
    """Tests for armadillo-flwr-approve-app."""

    def _run(self, fab, answer="APPROVE", auth_side_effect=None, add_side_effect=None):
        with patch(f"{TARGET}.console") as mock_console, patch(
            f"{TARGET}.build_whitelist_entry", return_value=ENTRY
        ) as mock_entry, patch(
            f"{TARGET}.armadillo_auth", return_value={"auth": ("a", "b")}, side_effect=auth_side_effect
        ), patch(f"{TARGET}.add_to_whitelist", side_effect=add_side_effect) as mock_add:
            mock_console.input.return_value = answer
            code = run_cli(approve_main, [str(fab), *APPROVE_ARGS])
        return code, mock_entry, mock_add

    def test_hashes_the_given_file_and_pushes_on_approve(self):
        code, mock_entry, mock_add = self._run("/reviews/publisher-app.fab")

        assert code == 0
        mock_entry.assert_called_once_with(Path("/reviews/publisher-app.fab"))
        mock_add.assert_called_once_with("http://localhost:8080", "c1", ENTRY, {"auth": ("a", "b")})

    def test_anything_but_approve_sends_nothing(self):
        code, _, mock_add = self._run("/reviews/publisher-app.fab", answer="no")

        assert code == 1
        mock_add.assert_not_called()

    def test_missing_credentials_exit_before_prompting(self):
        code, mock_entry, mock_add = self._run(
            "/reviews/publisher-app.fab", auth_side_effect=RuntimeError("No token")
        )

        assert code == 1
        mock_entry.assert_not_called()
        mock_add.assert_not_called()

    def test_server_error_exits_nonzero(self):
        code, _, _ = self._run(
            "/reviews/publisher-app.fab", add_side_effect=RuntimeError("no admin rights")
        )

        assert code == 1

    @patch(f"{TARGET}.console")
    @patch(f"{TARGET}.armadillo_auth", return_value={})
    def test_missing_fab_file_exits_without_traceback(self, mock_auth, mock_console, tmp_path):
        assert run_cli(approve_main, [str(tmp_path / "gone.fab"), *APPROVE_ARGS]) == 1
