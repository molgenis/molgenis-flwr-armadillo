"""Tests for the discovery module."""

from unittest.mock import MagicMock, patch

import pytest

from molgenis_flwr_armadillo.discovery import discover_nodes, handle_discovery


class TestHandleDiscovery:
    def test_returns_node_config(self):
        """handle_discovery should return a Message containing the node's config."""
        context = MagicMock()
        context.node_config = {"app-id": "study-a", "node-name": "node1"}

        message = MagicMock()

        result = handle_discovery(message, context)

        # The result should be a Message with reply_to set
        assert result.reply_to is message
        # The content should contain the node config as a ConfigRecord
        config = result.content["config"]
        assert config["app-id"] == "study-a"
        assert config["node-name"] == "node1"


class TestDiscoverNodes:
    def _make_reply(self, src_node_id, app_id=None):
        """Create a mock reply message from a node."""
        reply = MagicMock()
        reply.metadata.src_node_id = src_node_id

        config = {}
        if app_id is not None:
            config["app-id"] = app_id

        # RecordDict-like content with .get() support
        content = MagicMock()
        config_record = MagicMock()
        config_record.get.side_effect = lambda k, d=None: config.get(k, d)
        content.get.return_value = config_record
        reply.content = content

        return reply

    def test_filters_by_app_id(self):
        """discover_nodes should return only node IDs matching the app-id."""
        grid = MagicMock()
        grid.get_node_ids.return_value = [1, 2, 3]

        replies = [
            self._make_reply(1, app_id="study-a"),
            self._make_reply(2, app_id="study-a"),
            self._make_reply(3, app_id="study-b"),
        ]
        grid.send_and_receive.return_value = replies

        result = discover_nodes(grid, "study-a")

        assert sorted(result) == [1, 2]

    def test_raises_on_no_match(self):
        """discover_nodes should raise RuntimeError when no nodes match."""
        grid = MagicMock()
        grid.get_node_ids.return_value = [1, 2]

        replies = [
            self._make_reply(1, app_id="study-b"),
            self._make_reply(2, app_id="study-b"),
        ]
        grid.send_and_receive.return_value = replies

        with pytest.raises(RuntimeError, match="No nodes found with app-id='study-a'"):
            discover_nodes(grid, "study-a")

    def test_handles_missing_app_id(self):
        """Nodes without app-id in their config should be excluded."""
        grid = MagicMock()
        grid.get_node_ids.return_value = [1, 2, 3]

        replies = [
            self._make_reply(1, app_id="study-a"),
            self._make_reply(2, app_id=None),  # no app-id
            self._make_reply(3, app_id="study-a"),
        ]
        grid.send_and_receive.return_value = replies

        result = discover_nodes(grid, "study-a")

        assert sorted(result) == [1, 3]

    def test_sends_query_to_all_nodes(self):
        """discover_nodes should create a message for each connected node."""
        grid = MagicMock()
        grid.get_node_ids.return_value = [10, 20, 30]

        replies = [
            self._make_reply(10, app_id="study-a"),
            self._make_reply(20, app_id="study-a"),
            self._make_reply(30, app_id="study-a"),
        ]
        grid.send_and_receive.return_value = replies

        discover_nodes(grid, "study-a")

        assert grid.create_message.call_count == 3
        dst_ids = [
            call.kwargs["dst_node_id"]
            for call in grid.create_message.call_args_list
        ]
        assert sorted(dst_ids) == [10, 20, 30]
