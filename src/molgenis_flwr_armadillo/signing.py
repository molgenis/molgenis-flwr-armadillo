"""FAB signing and verification using Ed25519.

Signs Flower Application Bundles (FABs) so that SuperLink/SuperNode
wrappers can reject unsigned or untrusted code before execution.

Signing format (compatible with Flower's message signing convention):
    message = timestamp (8 bytes big-endian) + SHA-256(fab_content)
    signature = Ed25519.sign(message)
"""

from __future__ import annotations

import base64
import hashlib
import json
import time

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
)


def generate_keypair() -> tuple[Ed25519PrivateKey, Ed25519PublicKey]:
    """Generate an Ed25519 keypair for FAB signing."""
    private_key = Ed25519PrivateKey.generate()
    return private_key, private_key.public_key()


def derive_key_id(public_key: Ed25519PublicKey) -> str:
    """Derive a deterministic key ID from a public key.

    Format: 'fpk_' + first 8 hex chars of SHA-256(raw_public_key_bytes).
    """
    raw_bytes = public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)
    digest = hashlib.sha256(raw_bytes).hexdigest()
    return f"fpk_{digest[:8]}"


def sign_fab(
    fab_content: bytes, private_key: Ed25519PrivateKey
) -> dict[str, str]:
    """Sign FAB content and return a verifications dict.

    The returned dict is compatible with the Flower Fab dataclass
    ``verifications`` field.

    Returns::

        {
            "<key_id>": '{"signature": "<base64url>", "signed_at": <ts>}',
            "valid_license": "Valid"
        }
    """
    public_key = private_key.public_key()
    key_id = derive_key_id(public_key)

    timestamp = int(time.time())
    message = _build_message(fab_content, timestamp)
    signature = private_key.sign(message)

    sig_b64 = base64.urlsafe_b64encode(signature).decode()
    value = json.dumps({"signature": sig_b64, "signed_at": timestamp})

    return {key_id: value, "valid_license": "Valid"}


def verify_fab(
    fab_content: bytes,
    verifications: dict[str, str],
    trusted_keys: dict[str, Ed25519PublicKey],
) -> str:
    """Verify a FAB against trusted public keys.

    Returns ``"ok"`` if at least one trusted key produced a valid
    signature, or a human-readable reason string on failure.
    """
    if not verifications:
        return "no verifications provided (unsigned FAB)"

    # Collect key IDs present in the FAB for diagnostics
    fab_key_ids = [k for k in verifications if k != "valid_license"]

    matched_any = False
    for key_id, public_key in trusted_keys.items():
        payload = verifications.get(key_id)
        if payload is None:
            continue

        matched_any = True
        try:
            data = json.loads(payload)
            sig_bytes = base64.urlsafe_b64decode(data["signature"])
            timestamp = data["signed_at"]
        except (json.JSONDecodeError, KeyError, Exception):
            return f"malformed verification payload for key {key_id}"

        message = _build_message(fab_content, timestamp)
        try:
            public_key.verify(sig_bytes, message)
            return "ok"
        except Exception:
            return f"signature invalid for trusted key {key_id}"

    if not matched_any:
        return (
            f"no trusted key matched: FAB signed by {fab_key_ids}, "
            f"trusted keys are {list(trusted_keys.keys())}"
        )

    return "verification failed"


# ── helpers ──────────────────────────────────────────────────────────

def _build_message(fab_content: bytes, timestamp: int) -> bytes:
    """Build the canonical message: timestamp (8B BE) + SHA-256(content)."""
    ts_bytes = timestamp.to_bytes(8, byteorder="big")
    digest = hashlib.sha256(fab_content).digest()
    return ts_bytes + digest
