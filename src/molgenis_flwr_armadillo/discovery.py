"""App-aware node discovery for multi-tenant Flower deployments.

Provides a discovery protocol where the ServerApp queries all connected
supernodes for their node_config, then filters to only those matching
a given app-id. This enables multiple studies to share a single superlink
while ensuring training is dispatched only to the correct nodes.
"""

from flwr.app import ConfigRecord, Context, Message, RecordDict
from flwr.serverapp import Grid


def handle_discovery(message: Message, context: Context) -> Message:
    """Return this node's config in response to a discovery query."""
    return Message(
        content=RecordDict({"config": ConfigRecord(dict(context.node_config))}),
        reply_to=message,
    )


def discover_nodes(grid: Grid, app_id: str) -> list[int]:
    """Query all nodes and return IDs of those matching app_id."""
    all_ids = list(grid.get_node_ids())

    # Send discovery query to every node
    messages = [
        grid.create_message(
            content=RecordDict({"config": ConfigRecord({"type": "discover"})}),
            message_type="query",
            dst_node_id=nid,
            group_id="discovery",
        )
        for nid in all_ids
    ]
    replies = list(grid.send_and_receive(messages))

    # Filter by app-id
    matching = []
    for reply in replies:
        node_app_id = reply.content.get("config", {}).get("app-id", "")
        if node_app_id == app_id:
            matching.append(reply.metadata.src_node_id)

    if not matching:
        raise RuntimeError(
            f"No nodes found with app-id='{app_id}'. "
            f"Queried {len(all_ids)} nodes, none matched."
        )

    return matching
