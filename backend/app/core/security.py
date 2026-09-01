from hashlib import sha256

from argon2 import PasswordHasher, extract_parameters
from argon2.exceptions import InvalidHashError, VerificationError
from argon2.low_level import ARGON2_VERSION, Type


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


def validate_workspace_key_hash(encoded_hash: str) -> str:
    try:
        parameters = extract_parameters(encoded_hash)
    except InvalidHashError:
        raise ValueError(
            "Workspace Access Key hash must be a valid Argon2id hash."
        ) from None
    structurally_valid = (
        parameters.type is Type.ID
        and parameters.version == ARGON2_VERSION
        and parameters.salt_len >= 8
        and parameters.hash_len >= 16
        and 1 <= parameters.time_cost <= 10
        and 1 <= parameters.parallelism <= 16
        and 8 * parameters.parallelism
        <= parameters.memory_cost
        <= 1_048_576
    )
    if not structurally_valid:
        raise ValueError("Workspace Access Key hash must be a valid Argon2id hash.")
    return encoded_hash
