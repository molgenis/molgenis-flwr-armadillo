"""Tests for the FAB-hash whitelist SuperExec plugin."""

from unittest.mock import MagicMock, patch

import pytest
import yaml
from flwr.app import Message, RecordDict
from flwr.proto.task_pb2 import Task
from flwr.supercore.superexec.executor import LaunchResultStatus

from molgenis_flwr_armadillo.verified_exec_plugin import VerifiedClientAppExecPlugin

BASE_LAUNCH = "flwr.supercore.superexec.plugin.base_exec_plugin.BaseExecPlugin.launch_task"


def write_whitelist(path, hashes):
    """Write a whitelist file in Armadillo's format (#1066)."""
    entries = [{"fab_id": "publisher/app", "fab_version": "1.0.0", "fab_hash": h} for h in hashes]
    path.write_text(yaml.safe_dump(entries) if entries else "")


def new_plugin():
    return VerifiedClientAppExecPlugin(
        appio_api_address="127.0.0.1:9094",
        insecure=True,
        root_certificates_path=None,
        get_run=MagicMock(),
        executor=MagicMock(),
    )


@pytest.fixture
def whitelist(tmp_path):
    """Path to an initially empty whitelist file, loaded into a plugin."""
    path = tmp_path / "whitelist.yaml"
    write_whitelist(path, [])
    plugin = new_plugin()
    plugin.load_config({"fab_whitelist_path": str(path)})
    return path, plugin


def launch(plugin, fab_hash):
    """Launch a task, returning (result, base launch mock, rejection mock)."""
    with patch(BASE_LAUNCH) as mock_super, patch.object(plugin, "_report_rejection") as mock_report:
        result = plugin.launch_task("tok", Task(task_id=1, fab_hash=fab_hash))
    return result, mock_super, mock_report


def test_load_config_rejects_malformed_whitelist(tmp_path):
    path = tmp_path / "whitelist.yaml"
    path.write_text("- not a mapping\n")

    with pytest.raises(TypeError):
        new_plugin().load_config({"fab_whitelist_path": str(path)})


def test_rejects_everything_if_load_config_never_ran():
    result, mock_super, mock_report = launch(new_plugin(), "abc123")

    mock_super.assert_not_called()
    mock_report.assert_called_once()
    assert result.status == LaunchResultStatus.FAILED


def test_whitelisted_hash_launches(whitelist):
    path, plugin = whitelist
    write_whitelist(path, ["abc123"])

    _, mock_super, mock_report = launch(plugin, "abc123")

    mock_super.assert_called_once()
    mock_report.assert_not_called()


def test_unwhitelisted_hash_is_rejected(whitelist):
    path, plugin = whitelist
    write_whitelist(path, ["abc123"])

    result, mock_super, mock_report = launch(plugin, "not-approved")

    mock_super.assert_not_called()
    assert mock_report.call_args[0][0] == "tok"
    assert result.status == LaunchResultStatus.FAILED


def test_approval_after_start_takes_effect_without_restart(whitelist):
    path, plugin = whitelist
    assert launch(plugin, "abc123")[1].call_count == 0

    write_whitelist(path, ["abc123"])

    assert launch(plugin, "abc123")[1].call_count == 1


def test_unreadable_whitelist_rejects(whitelist):
    path, plugin = whitelist
    path.unlink()

    result, mock_super, _ = launch(plugin, "abc123")

    mock_super.assert_not_called()
    assert result.status == LaunchResultStatus.FAILED


def test_rejection_replies_with_an_error_message(whitelist):
    """Rejection pulls the task input and pushes an Error reply, as a real
    ClientApp exception does, so the ServerApp fails fast instead of timing out."""
    _, plugin = whitelist
    mock_channel, mock_stub, fake_context = MagicMock(), MagicMock(), MagicMock()
    original = Message(content=RecordDict(), dst_node_id=0, message_type="train")
    target = "molgenis_flwr_armadillo.verified_exec_plugin"

    with patch(f"{target}.create_channel", return_value=mock_channel), patch(
        f"{target}.ClientAppIoStub", return_value=mock_stub
    ), patch(
        f"{target}.pull_task_input", return_value=(original, fake_context, MagicMock(), MagicMock())
    ), patch(f"{target}.push_message") as mock_push:
        plugin.launch_task("tok", Task(task_id=1, fab_hash="not-approved"))

    stub_arg, reply_arg, context_arg = mock_push.call_args[0]
    assert stub_arg is mock_stub
    assert context_arg is fake_context
    assert "not-approved" in reply_arg.error.reason
    mock_channel.close.assert_called_once()


def test_rejection_reporting_errors_are_swallowed(whitelist):
    _, plugin = whitelist
    mock_channel = MagicMock()
    target = "molgenis_flwr_armadillo.verified_exec_plugin"

    with patch(f"{target}.create_channel", return_value=mock_channel), patch(
        f"{target}.ClientAppIoStub"
    ), patch(f"{target}.pull_task_input", side_effect=RuntimeError("boom")):
        result = plugin.launch_task("tok", Task(task_id=1, fab_hash="not-approved"))

    mock_channel.close.assert_called_once()
    assert result.status == LaunchResultStatus.FAILED
