import base64
import binascii
import hashlib
import hmac
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


@dataclass(frozen=True)
class EncryptedValue:
    ciphertext: bytes
    nonce: bytes


class SecretCipher:
    def __init__(self, key: bytes) -> None:
        if len(key) != 32:
            raise ValueError("The AES-256 master key must be exactly 32 bytes.")
        self._cipher = AESGCM(key)
        self._key = bytes(key)

    @classmethod
    def from_file(cls, path: Path) -> "SecretCipher":
        flags = os.O_RDONLY
        flags |= getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags)
        except OSError as error:
            raise ValueError("The master key file is unavailable.") from error

        try:
            try:
                file_status = os.fstat(descriptor)
                if not stat.S_ISREG(file_status.st_mode):
                    raise ValueError("The master key path must be a regular file.")
                if os.name == "posix":
                    if stat.S_IMODE(file_status.st_mode) != 0o600:
                        raise ValueError(
                            "The master key file permissions must be 0600."
                        )
                    if file_status.st_uid not in {0, os.geteuid()}:
                        raise ValueError("The master key file owner is not trusted.")
                encoded_key = _read_bounded(descriptor, limit=45)
            except OSError as error:
                raise ValueError("The master key file is unavailable.") from error
        finally:
            os.close(descriptor)

        try:
            key = base64.b64decode(encoded_key, validate=True)
        except (OSError, ValueError, binascii.Error) as error:
            raise ValueError(
                "The master key file must contain a valid base64-encoded 32-byte key."
            ) from error
        if len(key) != 32:
            raise ValueError(
                "The master key file must contain a valid base64-encoded 32-byte key."
            )
        return cls(key)

    def encrypt(self, plaintext: str) -> EncryptedValue:
        nonce = os.urandom(12)
        ciphertext = self._cipher.encrypt(nonce, plaintext.encode("utf-8"), None)
        return EncryptedValue(ciphertext=ciphertext, nonce=nonce)

    def decrypt(self, value: EncryptedValue) -> str:
        plaintext = self._cipher.decrypt(value.nonce, value.ciphertext, None)
        return plaintext.decode("utf-8")

    def derive_outreach_response_token(self, delivery_id: UUID) -> str:
        """Derive one re-creatable capability without exposing the master key."""

        if type(delivery_id) is not UUID or delivery_id.version != 4:
            raise ValueError("delivery_id must be a UUIDv4")
        material = hmac.new(
            self._key,
            b"find-me-gamer:outreach-response:v1\0" + delivery_id.bytes,
            hashlib.sha256,
        ).digest()
        return base64.urlsafe_b64encode(material).decode("ascii").rstrip("=")


def _read_bounded(descriptor: int, *, limit: int) -> bytes:
    chunks: list[bytes] = []
    remaining = limit
    while remaining:
        chunk = os.read(descriptor, remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)
