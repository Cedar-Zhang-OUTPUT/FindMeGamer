"""Offline provider failures: safe details survive without another send."""

import json
import time
from uuid import UUID

import httpx
import pytest

from test_graph_mail import graph_settings, graph_seed, MAILBOX


def attempt(tmp_path, response):
    from fmg_agent.email.graph import deliver

    settings = graph_settings(tmp_path)
    graph_seed(settings, time.time() + 3600)
    calls = []

    def respond(request):
        calls.append(request)
        return response

    result = deliver(
        settings,
        {
            "from": MAILBOX,
            "to": "private@example.com",
            "subject": "Private subject",
            "text": "Private message body",
        },
        "send-one",
        transport=httpx.MockTransport(respond),
    )
    assert len(calls) == 1
    return result, calls[0]


def test_429_preserves_safe_details_and_correlates_one_attempt(tmp_path, caplog):
    request_id = "81d7f35b-bf7f-4e34-95f9-91f3aa28fd75"
    with caplog.at_level("WARNING"):
        result, request = attempt(
            tmp_path,
            httpx.Response(
                429,
                headers={
                    "Retry-After": "120",
                    "request-id": request_id,
                    "Date": "Sat, 10 Oct 2026 05:00:00 GMT",
                },
                json={
                    "error": {
                        "code": "ErrorThrottled",
                        "message": "Mailbox send limit exceeded.",
                        "innerError": {"code": "MailSubmissionThrottled"},
                    }
                },
            ),
        )
    assert result["state"] == "failed"
    assert result["code"] == "graph_rate_limited"
    details = result["diagnostics"]
    assert details["provider"] == "microsoft_graph"
    assert details["http_status"] == 429
    assert details["provider_error_code"] == "ErrorThrottled"
    assert details["inner_error_code"] == "MailSubmissionThrottled"
    assert details["provider_message"] == "Mailbox send limit exceeded."
    assert details["retry_after_seconds"] == 120
    assert details["request_id"] == request_id
    assert details["response_date"] == "2026-10-10T05:00:00+00:00"
    assert UUID(details["client_request_id"])
    assert details["client_request_id"] == request.headers["client-request-id"]
    assert request.headers["return-client-request-id"] == "true"
    assert "graph_mail_response" in caplog.text
    assert request_id in caplog.text
    assert "private@example.com" not in caplog.text


def test_diagnostics_redacts_credentials_addresses_and_message_content(
    tmp_path, caplog
):
    text = (
        "Limit for private@example.com; Bearer graph-access; refresh_token=graph-refresh; "
        "Private subject; Private message body; https://example.com/?token=private; "
        + "x" * 1000
    )
    with caplog.at_level("WARNING"):
        result, _ = attempt(
            tmp_path,
            httpx.Response(
                429,
                json={
                    "error": {
                        "code": "ErrorThrottled",
                        "message": text,
                        "innerError": {
                            "request-id": "private@example.com",
                            "date": "secret",
                        },
                    }
                },
                headers={"Retry-After": "secret", "request-id": "secret"},
            ),
        )
    details = result["diagnostics"]
    combined = json.dumps(details) + caplog.text
    for secret in (
        "private@example.com",
        "graph-access",
        "graph-refresh",
        "Private subject",
        "Private message body",
        "https://example.com",
        "x" * 100,
    ):
        assert secret not in combined
    assert details["message_redacted"] is True
    assert len(details["provider_message"]) <= 512
    assert details["request_id"] is None
    assert details["retry_after_seconds"] is None


@pytest.mark.parametrize(
    "body",
    [
        b"not json private@example.com",
        b"[]",
        b'{"error": []}',
        b'{"error":{"message":{},"code":[]}}',
    ],
)
def test_malformed_details_never_change_failure_classification(tmp_path, body):
    result, _ = attempt(tmp_path, httpx.Response(503, content=body))
    assert result["state"] == "unknown"
    assert result["code"] == "graph_confirmation_lost"
    assert result["diagnostics"]["http_status"] == 503
    assert result["diagnostics"]["provider_error_code"] is None
    assert result["diagnostics"]["provider_message"] is None


def test_http_date_retry_after_is_recorded_without_wait_or_retry(tmp_path):
    result, _ = attempt(
        tmp_path,
        httpx.Response(
            429,
            headers={
                "Date": "Sat, 10 Oct 2026 05:00:00 GMT",
                "Retry-After": "Sat, 10 Oct 2026 05:01:00 GMT",
            },
        ),
    )
    assert result["diagnostics"]["retry_after_seconds"] == 60


@pytest.mark.parametrize(
    "prose",
    [
        "Invalid content: confidential budget is 45000 USD.",
        "Private message body with extra detail",
        "Unexpected undocumented provider prose",
    ],
)
def test_unknown_prose_is_withheld_even_when_it_only_echoes_an_excerpt(tmp_path, prose):
    result, _ = attempt(
        tmp_path,
        httpx.Response(
            429,
            json={
                "error": {
                    "code": "ErrorThrottled",
                    "message": prose,
                }
            },
        ),
    )
    details = result["diagnostics"]
    assert details["provider_message"] == "[withheld provider message]"
    assert details["message_redacted"] is True
    assert prose not in json.dumps(details)


@pytest.mark.parametrize(
    "code",
    ["graph-access", "Private-subject", "confidential-budget", "UnrecognizedCode"],
)
def test_unknown_error_codes_are_fingerprinted_not_stored_or_logged(
    tmp_path, code, caplog
):
    with caplog.at_level("WARNING"):
        result, _ = attempt(
            tmp_path,
            httpx.Response(
                429,
                json={
                    "error": {
                        "code": code,
                        "innerError": {"code": code},
                    }
                },
            ),
        )
    details = result["diagnostics"]
    assert details["provider_error_code"] is None
    assert details["inner_error_code"] is None
    assert len(details["provider_error_code_sha256"]) == 64
    assert code not in json.dumps(details) + caplog.text


def test_receipt_persists_diagnostics_and_replay_never_resends(sending):
    from test_email_sending import preview, send, headers

    app, client, owner, other, _ = sending
    calls = []
    details = {
        "provider": "microsoft_graph",
        "http_status": 429,
        "provider_error_code": "ErrorThrottled",
        "retry_after_seconds": 120,
    }

    def transport(*args):
        calls.append(1)
        return {"state": "failed", "code": "graph_rate_limited", "diagnostics": details}

    app.state.smtp_transport = transport
    pid = preview(client, owner).json()["data"]["id"]
    first = send(client, owner, pid).json()["data"]
    assert first["diagnostics"] == details
    assert (
        client.get(f"/v1/email/sends/{first['id']}", headers=headers(owner)).json()[
            "data"
        ]["diagnostics"]
        == details
    )
    assert send(client, owner, pid).json()["data"]["diagnostics"] == details
    assert (
        client.get(f"/v1/email/sends/{first['id']}", headers=headers(other)).status_code
        == 404
    )
    assert len(calls) == 1


# Share the real SQLite application fixture, replacing only external transport.
from test_email_sending import sending


def test_batch_query_exposes_only_its_recipients_diagnostics(sending):
    from test_outreach import create
    from test_email_sending import headers
    from fmg_agent.outreach import pending, process_recipient

    app, client, owner, other, _ = sending
    task = create(app, client, owner).json()["data"]
    path = "/v1/outreach/tasks/" + task["id"]
    client.post(
        path + "/start",
        headers=headers(owner),
        json={"confirm": True, "revision": task["revision"]},
    )
    ids = pending(app.state.sessions)
    process_recipient(
        app.state.sessions,
        ids[0],
        app.state.settings,
        lambda *args: {
            "state": "failed",
            "code": "graph_rate_limited",
            "diagnostics": {"provider": "microsoft_graph", "http_status": 429},
        },
    )
    result = client.get(path, headers=headers(owner)).json()["data"]
    rows = result["recipients"]
    assert sum(r["diagnostics"] is not None for r in rows) == 1
    assert (
        next(r for r in rows if r["state"] == "failed")["diagnostics"]["http_status"]
        == 429
    )
    assert client.get(path, headers=headers(other)).status_code == 404
