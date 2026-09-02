from uuid import UUID

from app.core.crypto import SecretCipher
from app.outreach.batches import response_token_digest


def test_response_capability_derivation_matches_literal_vector() -> None:
    cipher = SecretCipher(bytes(range(32)))
    delivery_id = UUID("12345678-1234-4abc-8def-1234567890ab")

    raw_token = cipher.derive_outreach_response_token(delivery_id)

    assert raw_token == "4VgXGmIrdluxpFv9pl5qyDaEr_AAva89GQ7AoYysuOQ"
    assert response_token_digest(raw_token) == (
        "78107be5774f3666ca349d382d023a3d5c1fd0116e63b86f5e2ecebc6ab63ae0"
    )
    assert "=" not in raw_token


def test_response_capabilities_are_bound_to_delivery_ids() -> None:
    cipher = SecretCipher(bytes(range(32)))

    first = cipher.derive_outreach_response_token(
        UUID("12345678-1234-4abc-8def-1234567890ab")
    )
    second = cipher.derive_outreach_response_token(
        UUID("12345678-1234-4abc-8def-1234567890ac")
    )

    assert first != second
    assert response_token_digest(first) != response_token_digest(second)
