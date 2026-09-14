import pytest


def test_creator_job_keys_do_not_collide():
    from app.analysis.creator_identity import creator_job_identity

    assert creator_job_identity("youtube", "UCexample123") == "UCexample123"
    assert creator_job_identity("x", "12345") == "x:12345"
    assert creator_job_identity("twitch", "12345") == "twitch:12345"
    assert creator_job_identity("instagram", "12345") == "instagram:12345"


@pytest.mark.parametrize(
    "platform,account",
    [("other", "123"), ("x", ""), ("x", " "), ("x", " 123"), ("x", "123 ")],
)
def test_invalid_creator_identity_is_rejected(platform, account):
    from app.analysis.creator_identity import creator_job_identity

    with pytest.raises(ValueError):
        creator_job_identity(platform, account)
