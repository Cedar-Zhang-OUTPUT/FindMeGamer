from tests.integration.test_activity_qualification import ready_composition, preview


def test_missing_sender_identity_is_explicit_in_send_qualification(auth_client, session, monkeypatch):
    _, composition = ready_composition(auth_client, session, monkeypatch, count=1, smtp=False)
    result = preview(auth_client, composition).json()
    assert not result["send_ready"]
    assert "sender_identity_missing" in result["members"][0]["missing_fields"]
