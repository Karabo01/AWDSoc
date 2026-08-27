"""AES-256-GCM envelope for tenant Wazuh credentials.

Stored form is `nonce || ciphertext || tag`, exactly as returned by the
cryptography AESGCM primitive, alongside a `key_version` column so a key can be
rotated by re-encrypting rows rather than by migrating the schema.

Decryption happens only inside the Manager API client. Never in a serialiser.
"""

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import settings

NONCE_BYTES = 12


class EncryptionError(RuntimeError):
    pass


def _key(version: int | None = None) -> bytes:
    version = version or settings.encryption_key_version
    if version != settings.encryption_key_version:
        raise EncryptionError(
            f"no key material for key_version={version} "
            f"(active is {settings.encryption_key_version})"
        )
    if not settings.encryption_key:
        raise EncryptionError("ENCRYPTION_KEY is not set")
    raw = base64.b64decode(settings.encryption_key)
    if len(raw) != 32:
        raise EncryptionError("ENCRYPTION_KEY must decode to exactly 32 bytes")
    return raw


def encrypt(plaintext: str) -> tuple[bytes, int]:
    """Returns (blob, key_version)."""
    nonce = os.urandom(NONCE_BYTES)
    blob = AESGCM(_key()).encrypt(nonce, plaintext.encode(), None)
    return nonce + blob, settings.encryption_key_version


def decrypt(blob: bytes, key_version: int) -> str:
    if len(blob) <= NONCE_BYTES:
        raise EncryptionError("ciphertext too short")
    nonce, payload = blob[:NONCE_BYTES], blob[NONCE_BYTES:]
    return AESGCM(_key(key_version)).decrypt(nonce, payload, None).decode()


def generate_key() -> str:
    """Convenience for onboarding: a fresh base64 ENCRYPTION_KEY."""
    return base64.b64encode(os.urandom(32)).decode()
