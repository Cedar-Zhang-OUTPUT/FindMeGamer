from uuid import UUID, uuid4
from sqlalchemy import select, func

from app.db.models.outreach import Delivery
from app.db.models.profiles import CreatorProfile, GameProfile
from app.db.models.discovery import Activity
from tests.integration.test_outreach_drafts import (
    draft_setup,
    compose,
    manual,
    confirm_facts,
    get_compose,
)
from tests.integration.test_activity_preparation import post, read, update


def configure_smtp(client, **changes):
    response = client.put(
        "/api/v1/outreach/smtp",
        json={
            "host": "smtp.example.com",
            "port": 465,
            "encryption": "tls",
            "username": "producer@example.com",
            "password": "fixture-password",
            "from_name": "Toki",
            "reply_to": "reply@example.com",
            "emails_per_minute": 10,
            **changes,
        },
    )
    assert response.status_code == 200, response.text


def ready_composition(
    client, session, monkeypatch, count=3, *, duplicate_email=False, smtp=True
):
    activity, choices, batch, template = draft_setup(
        client, session, monkeypatch, count=count
    )
    if smtp:
        configure_smtp(client)
        template = post(
            client,
            "/api/v2/outreach/template-versions/canonical",
            {"game_id": template["game_id"]},
        ).json()
    if count > 1:
        person = session.get(CreatorProfile, UUID(choices[1]["creator_id"]))
        if duplicate_email:
            person.contacts[0].email = "account-1@example.com"
            session.commit()
        response = update(
            client, read(client, choices[1]), contact_id=str(person.contacts[0].id)
        )
        assert response.status_code == 200, response.text
    composition = compose(client, activity, batch, template).json()
    edited = []
    for draft in composition["drafts"][:2]:
        response = manual(client, draft)
        assert response.status_code == 200, response.text
        edited.append(response.json())
    response = confirm_facts(client, composition["id"], edited)
    assert response.status_code == 200, response.text
    return activity, response.json()


def preview(client, composition, excluded=None):
    return post(
        client,
        f"/api/v2/outreach/compositions/{composition['id']}/qualification",
        {"excluded": excluded or []},
    )


def test_full_batch_qualification_keeps_n_and_explicit_exclusion_without_opening_each_email(
    auth_client, session, monkeypatch
):
    _, composition = ready_composition(auth_client, session, monkeypatch)
    response = preview(auth_client, composition)
    assert response.status_code == 200, response.text
    result = response.json()
    assert (
        result["total_count"],
        result["eligible_count"],
        result["repair_count"],
        result["excluded_count"],
    ) == (3, 2, 1, 0)
    assert not result["send_ready"]
    assert result["sender"] == {
        "address": "producer@example.com",
        "name": "Toki",
        "reply_to": "reply@example.com",
    }
    assert [m["status"] for m in result["members"]] == [
        "eligible",
        "eligible",
        "needs_repair",
    ]
    assert result["members"][1]["recipient_email"] == "account-2@example.com"
    assert "Thought you might enjoy" in result["members"][0]["subject"]
    assert "LIMINAL" not in result["members"][0]["html"]
    assert "Choice=" not in result["members"][0]["html"]
    assert "evaluation_missing" not in result["members"][0]["missing_fields"]
    excluded = [
        {
            "draft_id": composition["drafts"][2]["id"],
            "reason": "Need more recorded evidence",
        }
    ]
    accepted = preview(auth_client, composition, excluded).json()
    assert (
        accepted["total_count"],
        accepted["eligible_count"],
        accepted["repair_count"],
        accepted["excluded_count"],
    ) == (3, 2, 0, 1)
    assert accepted["send_ready"]
    assert accepted["members"][2]["exclusion_reason"] == "Need more recorded evidence"
    assert accepted["qualification_token"] != result["qualification_token"]
    assert preview(auth_client, composition, excluded).json() == accepted
    assert session.scalar(select(func.count()).select_from(Delivery)) == 0


def test_duplicate_email_requires_explicit_exclusion_not_silent_merge(
    auth_client, session, monkeypatch
):
    _, composition = ready_composition(
        auth_client, session, monkeypatch, count=2, duplicate_email=True
    )
    response = preview(auth_client, composition)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["eligible_count"] == 0 and result["repair_count"] == 2
    assert all(
        "duplicate_recipient_email" in m["missing_fields"] for m in result["members"]
    )
    second = composition["drafts"][1]["id"]
    repaired = preview(
        auth_client,
        composition,
        [{"draft_id": second, "reason": "Same management inbox"}],
    ).json()
    assert (
        repaired["total_count"] == 2
        and repaired["eligible_count"] == 1
        and repaired["send_ready"]
    )


def test_source_or_sender_change_invalidates_previous_qualification(
    auth_client, session, monkeypatch
):
    activity_id, composition = ready_composition(
        auth_client, session, monkeypatch, count=1
    )
    response = preview(auth_client, composition)
    assert response.status_code == 200, response.text
    before = response.json()
    game = session.get(GameProfile, session.get(Activity, UUID(activity_id)).game_id)
    game.manual_overrides = game.manual_overrides | {"description": "Changed game"}
    session.commit()
    changed = preview(auth_client, composition).json()
    assert changed["qualification_token"] != before["qualification_token"]
    assert (
        not changed["send_ready"]
        and "draft_sources_changed" in changed["members"][0]["missing_fields"]
    )
    configure_smtp(auth_client, username="new-sender@example.com")
    sender_changed = preview(auth_client, composition).json()
    assert sender_changed["qualification_token"] != changed["qualification_token"]
    assert sender_changed["sender"]["address"] == "new-sender@example.com"
    assert not sender_changed["send_ready"]


def test_missing_smtp_and_zero_eligible_are_not_sendable(
    auth_client, session, monkeypatch
):
    _, composition = ready_composition(
        auth_client, session, monkeypatch, count=1, smtp=False
    )
    response = preview(auth_client, composition)
    assert response.status_code == 200, response.text
    result = response.json()
    assert "smtp_not_configured" in result["members"][0]["missing_fields"]
    excluded = preview(
        auth_client,
        composition,
        [{"draft_id": composition["drafts"][0]["id"], "reason": "Do not send"}],
    ).json()
    assert (
        excluded["excluded_count"] == 1
        and excluded["eligible_count"] == 0
        and not excluded["send_ready"]
    )


def test_qualification_rejects_unknown_exclusions_and_requires_auth(
    auth_client, client, session, monkeypatch
):
    _, composition = ready_composition(auth_client, session, monkeypatch, count=1)
    assert (
        preview(
            auth_client,
            composition,
            [{"draft_id": str(uuid4()), "reason": "Not in this batch"}],
        ).status_code
        == 422
    )
    client.headers.pop("Authorization", None)
    assert preview(client, composition).status_code == 401
