from app.outreach.batches import response_token_digest


def test_response_token_digest_is_the_non_reversible_sha256_identity() -> None:
    raw_token = "A" * 43

    digest = response_token_digest(raw_token)

    assert digest == "0f007385b6f9d4b7eeb2748605afe1a984a0a3bfa3f014d09e2a784ce9e5cd1a"
    assert raw_token not in digest
