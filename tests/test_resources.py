"""Tests for the armadillo-flwr-resources CLI."""

import sys
from unittest.mock import patch

import pytest

from molgenis_flwr_armadillo.resources import build_resource_tree, main


def _labels(tree) -> list[str]:
    """Flatten a rich Tree into its labels, depth-first."""
    out = [str(tree.label)]
    for child in tree.children:
        out.extend(_labels(child))
    return out


class TestBuildResourceTree:
    """Tests for build_resource_tree."""

    @patch(
        "molgenis_flwr_armadillo.resources.list_resources",
        side_effect=lambda url, token, project: {"a": ["y.pt", "x.pt"], "b": []}[project],
    )
    @patch("molgenis_flwr_armadillo.resources.list_projects", return_value=["b", "a"])
    def test_lists_projects_and_resources_sorted(self, mock_projects, mock_resources):
        labels = _labels(build_resource_tree("http://h", "tok", None))

        assert labels == [
            "[cyan]http://h[/cyan]",
            "[green]a[/green]",
            "x.pt",
            "y.pt",
            "[green]b[/green]",
            "[dim]no resources[/dim]",
        ]

    @patch("molgenis_flwr_armadillo.resources.list_resources", return_value=["x.pt"])
    @patch("molgenis_flwr_armadillo.resources.check_access")
    def test_filters_to_requested_project(self, mock_check, mock_resources):
        labels = _labels(build_resource_tree("http://h", "tok", "a"))

        assert "[green]a[/green]" in labels
        mock_check.assert_called_once_with("http://h", "tok", "a")
        mock_resources.assert_called_once_with("http://h", "tok", "a")

    @patch("molgenis_flwr_armadillo.resources.check_access", side_effect=RuntimeError("no access"))
    def test_raises_when_requested_project_not_accessible(self, mock_check):
        with pytest.raises(RuntimeError, match="no access"):
            build_resource_tree("http://h", "tok", "zzz")

    @patch("molgenis_flwr_armadillo.resources.list_resources", side_effect=RuntimeError("boom"))
    @patch("molgenis_flwr_armadillo.resources.list_projects", return_value=["a"])
    def test_reports_resource_errors_inline(self, mock_projects, mock_resources):
        assert "[red]Error: boom[/red]" in _labels(build_resource_tree("http://h", "tok", None))

    @patch("molgenis_flwr_armadillo.resources.list_projects", return_value=[])
    def test_marks_node_with_no_projects(self, mock_projects):
        assert "[yellow]no accessible projects[/yellow]" in _labels(
            build_resource_tree("http://h", "tok", None)
        )


class TestMain:
    """Tests for the CLI entry point."""

    @patch("molgenis_flwr_armadillo.resources.console")
    @patch("molgenis_flwr_armadillo.resources.build_resource_tree")
    @patch(
        "molgenis_flwr_armadillo.resources.load_node_urls",
        return_value=["https://a.example.com", "https://b.example.com"],
    )
    @patch("molgenis_flwr_armadillo.resources.load_tokens", return_value={"a-example-com": "tokA"})
    def test_looks_up_token_by_sanitized_url_and_skips_missing(
        self, mock_tokens, mock_urls, mock_tree, mock_console
    ):
        with patch.object(sys, "argv", ["prog"]):
            main()

        mock_tree.assert_called_once_with("https://a.example.com", "tokA", None)
        printed = " ".join(str(c.args[0]) for c in mock_console.print.call_args_list if c.args)
        assert "No token for this node" in printed

    @patch("molgenis_flwr_armadillo.resources.console")
    @patch("molgenis_flwr_armadillo.resources.build_resource_tree")
    @patch("molgenis_flwr_armadillo.resources.load_node_urls", return_value=["https://a.example.com"])
    @patch("molgenis_flwr_armadillo.resources.load_tokens", return_value={"a-example-com": "tokA"})
    def test_passes_project_filter(self, mock_tokens, mock_urls, mock_tree, mock_console):
        with patch.object(sys, "argv", ["prog", "--project", "proj"]):
            main()

        mock_tree.assert_called_once_with("https://a.example.com", "tokA", "proj")

    @patch("molgenis_flwr_armadillo.resources.console")
    @patch(
        "molgenis_flwr_armadillo.resources.load_tokens",
        side_effect=FileNotFoundError("No tokens found"),
    )
    def test_exits_when_no_token_file(self, mock_tokens, mock_console):
        with patch.object(sys, "argv", ["prog"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1

    @pytest.mark.parametrize("error", [FileNotFoundError("flower-nodes.yaml"), ValueError("has no 'urls' list")])
    @patch("molgenis_flwr_armadillo.resources.console")
    @patch("molgenis_flwr_armadillo.resources.load_tokens", return_value={})
    def test_exits_when_config_missing_or_invalid(self, mock_tokens, mock_console, error):
        with patch("molgenis_flwr_armadillo.resources.load_node_urls", side_effect=error), patch.object(
            sys, "argv", ["prog"]
        ), pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1
