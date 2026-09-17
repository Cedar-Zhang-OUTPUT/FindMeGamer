from test_email_sending import sending, headers
from test_email_templates import variables


def create(app, client, owner, key="batch"):
    return client.post("/v1/outreach/tasks", headers=headers(owner, key), json={
        "name": "Launch", "template_id": "game-outreach", "template_version": "3",
        "recipients": [{"creator_id": name, "to": name + "@example.com", "variables": variables()}
                       for name in ("alice", "bob")],
    })


def test_approval_delivery_and_recipient_isolation(sending):
    app, client, owner, other, _ = sending
    task = create(app, client, owner).json()["data"]
    assert task["state"] == "awaiting_approval"
    assert create(app, client, owner).json()["data"]["id"] == task["id"]
    path = "/v1/outreach/tasks/" + task["id"]
    assert client.get(path, headers=headers(other)).status_code == 404
    assert client.post(path + "/start", headers=headers(owner), json={"confirm": True, "revision": "wrong"}).status_code == 409
    assert client.post(path + "/start", headers=headers(owner), json={"confirm": True, "revision": task["revision"]}).status_code == 200
    from fmg_agent.outreach import process_recipient, pending
    delivered = []
    def transport(*args):
        delivered.append(args[1])
        return {"state": "sent", "code": None}
    ids = pending(app.state.sessions)
    assert len(ids) == 2
    for rid in ids + ids:
        process_recipient(app.state.sessions, rid, app.state.settings, transport)
    assert len(delivered) == 2
    task = client.get(path, headers=headers(owner)).json()["data"]
    assert task["stats"]["sent"] == 2
    assert task["stats"]["reply_rate"] == 0
    assert all(r["reply_state"] == "no_reply" for r in task["recipients"])
    assert client.get("/v1/outreach/respond/retired?choice=yes").status_code == 404


def test_unconfirmed_and_unknown_never_resend(sending):
    app, client, owner, _, _ = sending
    task = create(app, client, owner).json()["data"]
    from fmg_agent.outreach import pending, process_recipient
    assert pending(app.state.sessions) == []
    path = "/v1/outreach/tasks/" + task["id"]
    assert client.post(path + "/start", headers=headers(owner), json={"confirm": False, "revision": task["revision"]}).status_code == 422
    client.post(path + "/start", headers=headers(owner), json={"confirm": True, "revision": task["revision"]})
    delivered = []
    def transport(*args):
        delivered.append(1)
        return {"state": "unknown", "code": "smtp_confirmation_lost"}
    for rid in pending(app.state.sessions):
        process_recipient(app.state.sessions, rid, app.state.settings, transport)
        process_recipient(app.state.sessions, rid, app.state.settings, transport)
    assert len(delivered) == 2
    result = client.get(path, headers=headers(owner)).json()["data"]
    assert result["state"] == "finished_with_issues"
    assert result["stats"]["unknown"] == 2


def test_concurrent_create_and_worker_delivery_are_idempotent(sending):
    from concurrent.futures import ThreadPoolExecutor
    from fmg_agent.outreach import pending, process_recipient
    app, client, owner, _, _ = sending
    with ThreadPoolExecutor(max_workers=3) as pool:
        responses = list(pool.map(lambda _: create(app, client, owner), range(3)))
    assert all(r.status_code == 201 for r in responses)
    assert len({r.json()["data"]["id"] for r in responses}) == 1
    task = responses[0].json()["data"]
    client.post("/v1/outreach/tasks/" + task["id"] + "/start", headers=headers(owner),
                json={"confirm": True, "revision": task["revision"]})
    count = []
    def transport(*args):
        count.append(1)
        return {"state": "sent", "code": None}
    rid = pending(app.state.sessions)[0]
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(lambda _: process_recipient(app.state.sessions, rid, app.state.settings, transport), range(3)))
    assert len(count) == 1


def test_invalid_recipient_and_missing_configuration(sending):
    app, client, owner, _, read = sending
    task = create(app, client, owner).json()["data"]
    path = "/v1/outreach/tasks/" + task["id"]
    assert client.get(path, headers=headers(read)).status_code == 403
    app.state.settings.smtp_host = ""
    assert client.post(path + "/start", headers=headers(owner), json={"confirm": True, "revision": task["revision"]}).status_code == 503
    assert client.get(path, headers=headers(owner)).json()["data"]["state"] == "awaiting_approval"
    payload = {"name": "invalid", "template_id": "game-outreach", "template_version": "3",
               "recipients": [{"creator_id": "x", "to": "not-an-address", "variables": variables()}]}
    assert client.post("/v1/outreach/tasks", headers=headers(owner, "invalid"), json=payload).status_code == 422
    payload["recipients"][0]["to"] = "x@example.com"
    payload["recipients"] *= 2
    assert client.post("/v1/outreach/tasks", headers=headers(owner, "duplicate"), json=payload).status_code == 422
