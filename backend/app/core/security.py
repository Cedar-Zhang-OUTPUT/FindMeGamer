from hashlib import sha256

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from argon2.low_level import Type


_workspace_key_hasher = PasswordHasher(type=Type.ID)


def hash_workspace_key(raw: str) -> str:
    return _workspace_key_hasher.hash(raw)


def verify_workspace_key(raw: str, encoded_hash: str) -> bool:
    try:
        return _workspace_key_hasher.verify(encoded_hash, raw)
    except (InvalidHashError, VerificationError):
        return False


def workspace_key_digest(raw: str) -> str:
    return sha256(raw.encode("utf-8")).hexdigest()
