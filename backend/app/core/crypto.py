import base64
import binascii
import os
import stat
from dataclasses import dataclass
from pathlib import Path

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

    @classmethod
    def from_file(cls, path: Path) -> "SecretCipher":
        try:
            file_status = path.lstat()
        except OSError as error:
            raise ValueError("The master key file is unavailable.") from error

        if not stat.S_ISREG(file_status.st_mode):
            raise ValueError("The master key path must be a regular file.")
        if os.name == "posix":
            if stat.S_IMODE(file_status.st_mode) != 0o600:
                raise ValueError("The master key file permissions must be 0600.")
            if file_status.st_uid not in {0, os.geteuid()}:
                raise ValueError("The master key file owner is not trusted.")

        try:
            encoded_key = path.read_bytes()
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
