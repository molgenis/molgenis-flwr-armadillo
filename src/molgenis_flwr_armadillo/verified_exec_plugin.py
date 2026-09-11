"""SuperExec plugin enforcing a FAB content-hash whitelist for ClientApps."""

from logging import ERROR
from pathlib import Path
from typing import Any

import yaml
from flwr.app import Message
from flwr.app.error import Error
from flwr.common.constant import ErrorCode
from flwr.common.logger import log
from flwr.proto.clientappio_pb2_grpc import ClientAppIoStub
from flwr.proto.task_pb2 import Task  # pylint: disable=E0611
from flwr.supercore.grpc import create_channel
from flwr.supercore.interceptors.appio_token_interceptor import (
    AppIoTokenClientInterceptor,
)
from flwr.supercore.superexec.executor import LaunchResult
from flwr.supercore.superexec.plugin import ClientAppExecPlugin
from flwr.supercore.tls import validate_and_resolve_root_certificates
from flwr.supernode.runtime.run_clientapp import pull_task_input, push_message


def read_whitelist(path: Path) -> set[str]:
    """Return the approved FAB hashes listed in the whitelist YAML file."""
    with open(path, encoding="utf-8") as file:
        entries = yaml.safe_load(file) or []
    return {entry["fab_hash"] for entry in entries}


class VerifiedClientAppExecPlugin(ClientAppExecPlugin):
    """ClientApp SuperExec plugin that only launches whitelisted FABs.

    ``select_task`` is left at the default (first-candidate) behaviour so
    tasks are always claimed; rejection happens in ``launch_task``, once a
    token is available, so an error reply can be pushed back immediately
    instead of leaving the task to silently expire.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._whitelist_path: Path | None = None

    def load_config(self, yaml_config: dict[str, Any]) -> None:
        """Store the whitelist path, reading it once so a malformed file fails at startup."""
        self._whitelist_path = Path(yaml_config["fab_whitelist_path"])
        read_whitelist(self._whitelist_path)

    def launch_task(self, token: str, task: Task) -> LaunchResult:
        """Launch the task if its FAB hash is whitelisted, else reject it."""
        # Read per task: Armadillo rewrites the file on every approval, and
        # approvals must take effect without restarting the container.
        if self._is_whitelisted(task.fab_hash):
            return super().launch_task(token, task)

        message = f"FAB hash {task.fab_hash} is not on the approved whitelist"
        log(ERROR, message)
        self._report_rejection(token, message)
        return LaunchResult.failed(message)

    def _is_whitelisted(self, fab_hash: str) -> bool:
        """Return whether fab_hash is approved; any unreadable whitelist means no."""
        if self._whitelist_path is None or not fab_hash:
            return False
        try:
            return fab_hash in read_whitelist(self._whitelist_path)
        except Exception as err:  # noqa: BLE001 — fail closed on any read/parse error
            log(ERROR, "Cannot read FAB whitelist %s: %s", self._whitelist_path, err)
            return False

    def _report_rejection(self, token: str, details: str) -> None:
        """Reply to the pending task so the ServerApp sees the rejection
        immediately. A plain status update (PushTaskOutput) isn't enough —
        only an actual reply Message unblocks the ServerApp's aggregation
        wait, so this pulls the task's input (for its Message/Context, needed
        to build a reply) and pushes an error reply, mirroring exactly what
        run_clientapp.py does for a real ClientApp exception.
        """
        channel = create_channel(
            server_address=self.appio_api_address,
            insecure=self.insecure,
            root_certificates=validate_and_resolve_root_certificates(
                self.root_certificates_path, self.insecure
            ),
            interceptors=[AppIoTokenClientInterceptor(token)],
        )
        try:
            stub = ClientAppIoStub(channel)
            message, context, _run, _fab = pull_task_input(stub)
            reply = Message(
                Error(code=ErrorCode.CLIENT_APP_RAISED_EXCEPTION, reason=details),
                reply_to=message,
            )
            push_message(stub, reply, context)
        except Exception as err:  # noqa: BLE001 — never let reporting break the SuperExec loop
            log(ERROR, "Failed to report FAB whitelist rejection: %s", err)
        finally:
            channel.close()
