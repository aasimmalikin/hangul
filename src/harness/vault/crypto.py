"""Encryption at rest for vault credentials.

``Cipher`` is the seam for a KMS later; ``FernetCipher`` is what ships now
(AES-128-CBC + HMAC, key from ``settings.vault_master_key``)."""

import hashlib
from typing import Protocol

from cryptography.fernet import Fernet, InvalidToken


class Cipher(Protocol):
    def encrypt(self, plaintext: str) -> str: ...
    def decrypt(self, ciphertext: str) -> str: ...


class FernetCipher:
    def __init__(self, master_key: str) -> None:
        try:
            self._f = Fernet(master_key.encode() if isinstance(master_key, str) else master_key)
        except (ValueError, TypeError) as e:
            raise ValueError("vault_master_key must be a urlsafe base64 32-byte Fernet key") from e

    def encrypt(self, plaintext: str) -> str:
        return self._f.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        try:
            return self._f.decrypt(ciphertext.encode()).decode()
        except InvalidToken as e:
            raise ValueError("ciphertext cannot be decrypted with this master key") from e


def generate_master_key() -> str:
    return Fernet.generate_key().decode()


def fingerprint(secret: str, length: int = 12) -> str:
    """Stable, non-reversible id for a secret: used for duplicate detection
    and for the ``[REDACTED:...]`` marker. Never store more than this."""
    return hashlib.sha256(secret.encode()).hexdigest()[:length]
