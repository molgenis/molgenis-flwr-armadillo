"""FedAvg wrapper that restricts node selection to discovered nodes."""

from flwr.serverapp.strategy import FedAvg


class MolgenisFedAvg(FedAvg):
    """FedAvg that only dispatches to pre-filtered node IDs."""

    def __init__(self, node_ids: list[int], **kwargs):
        super().__init__(**kwargs)
        self._node_ids = set(node_ids)

    def configure_train(self, server_round, arrays, config, grid):
        messages = list(super().configure_train(server_round, arrays, config, grid))
        return [m for m in messages if m.metadata.dst_node_id in self._node_ids]

    def configure_evaluate(self, server_round, arrays, config, grid):
        messages = list(super().configure_evaluate(server_round, arrays, config, grid))
        return [m for m in messages if m.metadata.dst_node_id in self._node_ids]
