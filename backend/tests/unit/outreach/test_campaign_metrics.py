from decimal import Decimal

from app.outreach.metrics import (
    CampaignMetrics,
    DeliveryProjection,
    calculate_campaign_metrics,
    derive_campaign_state,
)


def test_campaign_metrics_count_unique_creators_across_resends() -> None:
    rows = [
        DeliveryProjection(
            creator_id="creator-a",
            send_state="sent",
            response_state="accepted",
            is_current=False,
        ),
        DeliveryProjection(
            creator_id="creator-a",
            send_state="sent",
            response_state="accepted",
            is_current=True,
        ),
        DeliveryProjection(
            creator_id="creator-b",
            send_state="failed",
            response_state="no_response",
            is_current=True,
        ),
        DeliveryProjection(
            creator_id="creator-c",
            send_state="sent",
            response_state="no_response",
            is_current=True,
        ),
    ]

    assert calculate_campaign_metrics(rows) == CampaignMetrics(
        sent_creators=2,
        accepted=1,
        declined=0,
        no_response=1,
        failed=1,
        response_rate=Decimal("0.5"),
    )


def test_prior_success_followed_by_failed_resend_is_sent_not_failed() -> None:
    metrics = calculate_campaign_metrics(
        [
            DeliveryProjection(
                creator_id="creator-a",
                send_state="sent",
                response_state="no_response",
                is_current=False,
            ),
            DeliveryProjection(
                creator_id="creator-a",
                send_state="failed",
                response_state="no_response",
                is_current=True,
            ),
        ]
    )

    assert metrics == CampaignMetrics(
        sent_creators=1,
        accepted=0,
        declined=0,
        no_response=1,
        failed=0,
        response_rate=Decimal("0"),
    )


def test_queued_and_sending_creators_do_not_enter_any_metric() -> None:
    metrics = calculate_campaign_metrics(
        [
            DeliveryProjection("creator-a", "queued", "no_response", True),
            DeliveryProjection("creator-b", "sending", "no_response", True),
        ]
    )

    assert metrics == CampaignMetrics(
        sent_creators=0,
        accepted=0,
        declined=0,
        no_response=0,
        failed=0,
        response_rate=Decimal("0"),
    )


def test_metrics_are_independent_of_history_order_and_duplicate_rows() -> None:
    history = [
        DeliveryProjection("creator-a", "sent", "declined", False),
        DeliveryProjection("creator-a", "failed", "declined", True),
        DeliveryProjection("creator-b", "failed", "no_response", True),
    ]

    expected = CampaignMetrics(
        sent_creators=1,
        accepted=0,
        declined=1,
        no_response=0,
        failed=1,
        response_rate=Decimal("1"),
    )
    assert calculate_campaign_metrics(history) == expected
    assert calculate_campaign_metrics([*reversed(history), *history]) == expected


def test_campaign_state_uses_current_delivery_precedence_and_prior_success() -> None:
    assert derive_campaign_state([]) == "not_started"
    assert (
        derive_campaign_state(
            [DeliveryProjection("creator-a", "failed", is_current=True)]
        )
        == "failed"
    )
    assert (
        derive_campaign_state(
            [
                DeliveryProjection("creator-a", "sent", is_current=False),
                DeliveryProjection("creator-a", "failed", is_current=True),
            ]
        )
        == "completed"
    )
    assert (
        derive_campaign_state(
            [
                DeliveryProjection("creator-a", "sent", is_current=False),
                DeliveryProjection("creator-a", "queued", is_current=True),
            ]
        )
        == "queued"
    )
    assert (
        derive_campaign_state(
            [
                DeliveryProjection("creator-a", "queued", is_current=True),
                DeliveryProjection("creator-b", "sending", is_current=True),
            ]
        )
        == "sending"
    )
