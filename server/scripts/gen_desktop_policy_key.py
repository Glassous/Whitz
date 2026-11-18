"""Generate the Ed25519 key pair used to sign desktop policy envelopes.

Usage:
    python scripts/gen_desktop_policy_key.py

Prints the base64 private key for ``DESKTOP_POLICY_PRIVATE_KEY`` and writes the
public key to ``desktop/resources/policy_pubkey.pem`` so the desktop build can
verify the envelope. Keep the private key only in the server environment.
"""

from __future__ import annotations

import base64
import pathlib

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = pathlib.Path(__file__).resolve().parents[2]


def main() -> None:
    key = Ed25519PrivateKey.generate()
    seed = base64.b64encode(
        key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
    ).decode("ascii")
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    public_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")

    target = ROOT / "desktop" / "resources" / "policy_pubkey.pem"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(public_pem, encoding="utf-8")

    print("DESKTOP_POLICY_PRIVATE_KEY=" + seed)
    print()
    print("PEM form (for secret managers that prefer PEM):")
    print(private_pem)
    print(f"Public key written to: {target}")


if __name__ == "__main__":
    main()
