import base64
import os

import pytest
from cryptography.exceptions import InvalidTag

from app.core.crypto import EncryptedValue, SecretCipher


def test_aes_gcm_round_trip_and_random_nonce() -> None:
    cipher = SecretCipher(bytes(range(32)))

    one = cipher.encrypt("secret")
    two = cipher.encrypt("secret")

    assert one.nonce != two.nonce
    assert cipher.decrypt(one) == "secret"


def test_aes_gcm_rejects_tampered_ciphertext() -> None:
    cipher = SecretCipher(bytes(range(32)))
    encrypted = cipher.encrypt("credential")
    tampered = EncryptedValue(
        ciphertext=bytes([encrypted.ciphertext[0] ^ 1]) + encrypted.ciphertext[1:],
        nonce=encrypted.nonce,
    )

    with pytest.raises(InvalidTag):
        cipher.decrypt(tampered)


@pytest.mark.parametrize("key_size", [0, 16, 31, 33])
def test_cipher_requires_exactly_32_key_bytes(key_size: int) -> None:
    with pytest.raises(ValueError, match="32 bytes"):
        SecretCipher(bytes(key_size))


def test_cipher_loads_strict_base64_key_from_private_file(tmp_path) -> None:
    key_file = tmp_path / "master.key"
    key_file.write_bytes(base64.b64encode(bytes(range(32))))
    key_file.chmod(0o600)

    cipher = SecretCipher.from_file(key_file)

    assert cipher.decrypt(cipher.encrypt("loaded-secret")) == "loaded-secret"


@pytest.mark.parametrize(
    "contents",
    [
        b"not base64!",
        base64.b64encode(bytes(31)),
        base64.b64encode(bytes(33)),
        base64.b64encode(bytes(32)) + b"\n",
        base64.b64encode(bytes(32)) + b"=",
        base64.b64encode(bytes(32)) + b"extra",
    ],
)
def test_cipher_rejects_malformed_or_extra_key_file_data(tmp_path, contents: bytes) -> None:
    key_file = tmp_path / "master.key"
    key_file.write_bytes(contents)
    key_file.chmod(0o600)

    with pytest.raises(ValueError, match="valid base64-encoded 32-byte key"):
        SecretCipher.from_file(key_file)


@pytest.mark.skipif(os.name != "posix", reason="POSIX file mode requirement")
def test_cipher_rejects_key_file_readable_by_group_or_others(tmp_path) -> None:
    key_file = tmp_path / "master.key"
    key_file.write_bytes(base64.b64encode(bytes(range(32))))
    key_file.chmod(0o640)

    with pytest.raises(ValueError, match="permissions"):
        SecretCipher.from_file(key_file)
