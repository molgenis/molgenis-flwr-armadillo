"""Tests for the MolgenisFedAvg strategy."""

from unittest.mock import MagicMock, patch

from molgenis_flwr_armadillo.strategy import MolgenisFedAvg


class TestMolgenisFedAvg:
    def _make_message(self, dst_node_id):
        """Create a mock message with a destination node ID."""
        msg = MagicMock()
        msg.metadata.dst_node_id = dst_node_id
        return msg

    @patch.object(MolgenisFedAvg, "__init__", lambda self, **kwargs: None)
    def test_configure_train_filters_nodes(self):
        """configure_train should only return messages for matching node IDs."""
        strategy = MolgenisFedAvg()
        strategy._node_ids = {1, 2}
        strategy.fraction_train = 1.0

        messages = [
            self._make_message(1),
            self._make_message(2),
            self._make_message(3),
        ]

        with patch(
            "flwr.serverapp.strategy.FedAvg.configure_train",
            return_value=messages,
        ):
            result = strategy.configure_train(
                server_round=1,
                arrays=MagicMock(),
                config=MagicMock(),
                grid=MagicMock(),
            )

        assert len(result) == 2
        dst_ids = [m.metadata.dst_node_id for m in result]
        assert sorted(dst_ids) == [1, 2]

    @patch.object(MolgenisFedAvg, "__init__", lambda self, **kwargs: None)
    def test_configure_evaluate_filters_nodes(self):
        """configure_evaluate should only return messages for matching node IDs."""
        strategy = MolgenisFedAvg()
        strategy._node_ids = {1, 2}
        strategy.fraction_evaluate = 1.0

        messages = [
            self._make_message(1),
            self._make_message(2),
            self._make_message(3),
        ]

        with patch(
            "flwr.serverapp.strategy.FedAvg.configure_evaluate",
            return_value=messages,
        ):
            result = strategy.configure_evaluate(
                server_round=1,
                arrays=MagicMock(),
                config=MagicMock(),
                grid=MagicMock(),
            )

        assert len(result) == 2
        dst_ids = [m.metadata.dst_node_id for m in result]
        assert sorted(dst_ids) == [1, 2]

    def test_init_stores_node_ids_as_set(self):
        """__init__ should store node_ids as a set for efficient lookup."""
        with patch("flwr.serverapp.strategy.FedAvg.__init__", return_value=None):
            strategy = MolgenisFedAvg(node_ids=[1, 2, 3])

        assert strategy._node_ids == {1, 2, 3}

    @patch.object(MolgenisFedAvg, "__init__", lambda self, **kwargs: None)
    def test_configure_train_empty_when_no_match(self):
        """configure_train returns empty list when no messages match."""
        strategy = MolgenisFedAvg()
        strategy._node_ids = {99}

        messages = [
            self._make_message(1),
            self._make_message(2),
        ]

        with patch(
            "flwr.serverapp.strategy.FedAvg.configure_train",
            return_value=messages,
        ):
            result = strategy.configure_train(
                server_round=1,
                arrays=MagicMock(),
                config=MagicMock(),
                grid=MagicMock(),
            )

        assert result == []
