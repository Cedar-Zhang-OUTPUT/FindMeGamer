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


@pytest.mark.skipif(os.name != "posix", reason="POSIX no-follow requirement")
def test_cipher_rejects_symlink_key_file(tmp_path) -> None:
    target = tmp_path / "target.key"
    target.write_bytes(base64.b64encode(bytes(range(32))))
    target.chmod(0o600)
    key_file = tmp_path / "master.key"
    key_file.symlink_to(target)

    with pytest.raises(ValueError):
        SecretCipher.from_file(key_file)


def test_cipher_validates_and_reads_the_same_open_descriptor(
    tmp_path, monkeypatch
) -> None:
    original_key = bytes(range(32))
    replacement_key = bytes(reversed(range(32)))
    key_file = tmp_path / "master.key"
    key_file.write_bytes(base64.b64encode(original_key))
    key_file.chmod(0o600)
    replacement = tmp_path / "replacement.key"
    replacement.write_bytes(base64.b64encode(replacement_key))
    replacement.chmod(0o644)
    real_open = os.open
    opened_descriptors: list[int] = []

    def open_then_replace(path, flags):
        descriptor = real_open(path, flags)
        opened_descriptors.append(descriptor)
        os.replace(replacement, key_file)
        return descriptor

    monkeypatch.setattr("app.core.crypto.os.open", open_then_replace)

    cipher = SecretCipher.from_file(key_file)
    original_value = SecretCipher(original_key).encrypt("original-key-loaded")

    assert cipher.decrypt(original_value) == "original-key-loaded"
    assert len(opened_descriptors) == 1
    with pytest.raises(OSError):
        os.fstat(opened_descriptors[0])


def test_cipher_closes_descriptor_when_validation_fails(tmp_path, monkeypatch) -> None:
    key_file = tmp_path / "master.key"
    key_file.write_bytes(base64.b64encode(bytes(range(32))))
    key_file.chmod(0o644)
    real_open = os.open
    opened_descriptors: list[int] = []

    def record_open(path, flags):
        descriptor = real_open(path, flags)
        opened_descriptors.append(descriptor)
        return descriptor

    monkeypatch.setattr("app.core.crypto.os.open", record_open)

    with pytest.raises(ValueError, match="permissions"):
        SecretCipher.from_file(key_file)

    assert len(opened_descriptors) == 1
    with pytest.raises(OSError):
        os.fstat(opened_descriptors[0])


def test_cipher_closes_descriptor_and_sanitizes_read_failure(
    tmp_path, monkeypatch
) -> None:
    key_file = tmp_path / "master.key"
    key_file.write_bytes(base64.b64encode(bytes(range(32))))
    key_file.chmod(0o600)
    real_open = os.open
    opened_descriptors: list[int] = []

    def record_open(path, flags):
        descriptor = real_open(path, flags)
        opened_descriptors.append(descriptor)
        return descriptor

    def fail_read(descriptor: int, count: int) -> bytes:
        raise OSError("filesystem detail must stay private")

    monkeypatch.setattr("app.core.crypto.os.open", record_open)
    monkeypatch.setattr("app.core.crypto.os.read", fail_read)

    with pytest.raises(ValueError, match="unavailable"):
        SecretCipher.from_file(key_file)

    assert len(opened_descriptors) == 1
    with pytest.raises(OSError):
        os.fstat(opened_descriptors[0])
