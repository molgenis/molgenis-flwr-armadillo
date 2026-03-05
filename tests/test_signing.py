"""Tests for FAB signing and verification."""

import json

from molgenis_flwr_armadillo.signing import (
    derive_key_id,
    generate_keypair,
    sign_fab,
    verify_fab,
)

SAMPLE_FAB = b"fake-fab-bundle-content-for-testing"


class TestSignFab:
    def test_roundtrip(self):
        """Sign then verify with the same keypair succeeds."""
        priv, pub = generate_keypair()
        verifications = sign_fab(SAMPLE_FAB, priv)
        trusted = {derive_key_id(pub): pub}
        assert verify_fab(SAMPLE_FAB, verifications, trusted) is True

    def test_produces_valid_format(self):
        """Verifications dict has key_id → JSON with signature and signed_at."""
        priv, pub = generate_keypair()
        verifications = sign_fab(SAMPLE_FAB, priv)
        key_id = derive_key_id(pub)

        assert key_id in verifications
        data = json.loads(verifications[key_id])
        assert "signature" in data
        assert "signed_at" in data
        assert isinstance(data["signed_at"], int)

    def test_includes_valid_license(self):
        """Verifications dict contains the valid_license field."""
        priv, _ = generate_keypair()
        verifications = sign_fab(SAMPLE_FAB, priv)
        assert verifications["valid_license"] == "Valid"

    def test_rejects_tampered_content(self):
        """Altering FAB content after signing causes verification to fail."""
        priv, pub = generate_keypair()
        verifications = sign_fab(SAMPLE_FAB, priv)
        trusted = {derive_key_id(pub): pub}
        assert verify_fab(b"tampered-content", verifications, trusted) is False

    def test_rejects_untrusted_signer(self):
        """Signing with key A, verifying with key B fails."""
        priv_a, _ = generate_keypair()
        _, pub_b = generate_keypair()
        verifications = sign_fab(SAMPLE_FAB, priv_a)
        trusted = {derive_key_id(pub_b): pub_b}
        assert verify_fab(SAMPLE_FAB, verifications, trusted) is False

    def test_rejects_empty_verifications(self):
        """Empty verifications dict is always rejected."""
        _, pub = generate_keypair()
        trusted = {derive_key_id(pub): pub}
        assert verify_fab(SAMPLE_FAB, {}, trusted) is False

    def test_derive_key_id_deterministic(self):
        """Same public key always produces the same key ID."""
        _, pub = generate_keypair()
        assert derive_key_id(pub) == derive_key_id(pub)

    def test_different_content_different_signature(self):
        """Different FAB content produces different signatures."""
        priv, _ = generate_keypair()
        v1 = sign_fab(b"content-a", priv)
        v2 = sign_fab(b"content-b", priv)
        key_id = [k for k in v1 if k != "valid_license"][0]
        sig1 = json.loads(v1[key_id])["signature"]
        sig2 = json.loads(v2[key_id])["signature"]
        assert sig1 != sig2
