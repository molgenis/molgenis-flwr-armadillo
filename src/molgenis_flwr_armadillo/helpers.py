"""Helper functions for token handling in Flower apps."""

from flwr.app import Context, Message


def extract_tokens(context: Context) -> dict:
    """Extract all tokens from run_config for passing to clients.

    Use in server_app.py to collect tokens for the train_config.

    Args:
        context: The Flower Context object

    Returns:
        Dict of token keys to token values, e.g. {"token-demo": "eyJ..."}

    Example:
        from molgenis_flwr_armadillo import extract_tokens

        @app.main()
        def main(grid: Grid, context: Context) -> None:
            lr = context.run_config["learning-rate"]
            tokens = extract_tokens(context)
            train_config = ConfigRecord({"lr": lr, **tokens})
            # ...
    """
    return {k: v for k, v in context.run_config.items() if k.startswith("token-")}


def get_node_token(msg: Message, context: Context) -> str:
    """Extract this node's token from the message config.

    Use in client_app.py to get the token for this specific node.

    Args:
        msg: The Flower Message received from the server
        context: The Flower Context object

    Returns:
        The token string for this node, or empty string if not found

    Example:
        from molgenis_flwr_armadillo import get_node_token

        @app.train()
        def train(msg: Message, context: Context):
            token = get_node_token(msg, context)
            data = fetch_from_armadillo(token)
            # ...
    """
    node_name = context.node_config.get("node-name", "")
    return msg.content.get("config", {}).get(f"token-{node_name}", "")