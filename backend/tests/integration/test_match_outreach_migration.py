from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import DateTime, inspect, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.engine import Connection, Inspector
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.base import Base


MATCH_TABLES = {
    "match_tasks",
    "match_screening_records",
    "match_candidate_inputs",
    "match_pairwise_records",
    "match_result_items",
}
OUTREACH_TABLES = {
    "outreach_campaigns",
    "templates",
    "send_batches",
    "deliveries",
    "campaign_creator_responses",
}
TASK_ONE_TABLES = MATCH_TABLES | OUTREACH_TABLES

EXPECTED_COLUMNS = {
    "match_tasks": {
        "id",
        "game_id",
        "locked_game_brief",
        "shuffle_seed",
        "recommended_match_threshold",
        "status",
        "stage",
        "completed_units",
        "total_units",
        "result_count",
        "error_code",
        "error_message",
        "retryable",
        "correlation_id",
        "input_expires_at",
        "ranking_enqueued_at",
        "started_at",
        "completed_at",
        "supersedes_id",
        "created_at",
        "updated_at",
    },
    "match_screening_records": {
        "id",
        "match_task_id",
        "creator_id",
        "screening_order",
        "locked_creator_brief",
        "selected",
        "screening_reason",
        "expires_at",
        "created_at",
        "updated_at",
    },
    "match_candidate_inputs": {
        "id",
        "match_task_id",
        "creator_id",
        "locked_creator_profile",
        "input_model_metadata",
        "input_prompt_metadata",
        "expires_at",
        "created_at",
        "updated_at",
    },
    "match_pairwise_records": {
        "id",
        "match_task_id",
        "creator_id",
        "state",
        "attempt_count",
        "match_brief",
        "error_code",
        "error_message",
        "retryable",
        "started_at",
        "completed_at",
        "created_at",
        "updated_at",
    },
    "match_result_items": {
        "id",
        "match_task_id",
        "creator_id",
        "backend_order",
        "match_brief",
        "total_score",
        "dimension_scores",
        "dimension_outcomes",
        "match_reasons",
        "result_group",
        "qualitative_label",
        "created_at",
        "updated_at",
    },
    "outreach_campaigns": {
        "id",
        "match_task_id",
        "created_at",
        "updated_at",
    },
    "templates": {
        "id",
        "name",
        "version",
        "subject_template",
        "body_markdown",
        "accepted_label",
        "declined_label",
        "is_default",
        "created_at",
        "updated_at",
    },
    "send_batches": {
        "id",
        "campaign_id",
        "template_id",
        "requested_creator_ids",
        "requested_at",
        "state",
        "created_at",
        "updated_at",
    },
    "deliveries": {
        "id",
        "campaign_id",
        "send_batch_id",
        "creator_id",
        "resends_delivery_id",
        "recipient_email",
        "rendered_subject",
        "rendered_markdown",
        "rendered_html",
        "template_name",
        "template_version",
        "accepted_label",
        "declined_label",
        "sender_name",
        "sender_address",
        "reply_to",
        "send_state",
        "response_state",
        "smtp_error_code",
        "smtp_error_message",
        "smtp_retryable",
        "response_token_digest",
        "sending_at",
        "sent_at",
        "failed_at",
        "responded_at",
        "superseded_at",
        "created_at",
        "updated_at",
    },
    "campaign_creator_responses": {
        "id",
        "campaign_id",
        "creator_id",
        "state",
        "final_delivery_id",
        "responded_at",
        "created_at",
        "updated_at",
    },
}

JSON_COLUMNS = {
    ("match_tasks", "locked_game_brief"),
    ("match_screening_records", "locked_creator_brief"),
    ("match_candidate_inputs", "locked_creator_profile"),
    ("match_candidate_inputs", "input_model_metadata"),
    ("match_candidate_inputs", "input_prompt_metadata"),
    ("match_pairwise_records", "match_brief"),
    ("match_result_items", "match_brief"),
    ("match_result_items", "dimension_scores"),
    ("match_result_items", "dimension_outcomes"),
    ("match_result_items", "match_reasons"),
    ("send_batches", "requested_creator_ids"),
}

TIMESTAMP_COLUMNS = {
    "created_at",
    "updated_at",
    "input_expires_at",
    "expires_at",
    "ranking_enqueued_at",
    "started_at",
    "completed_at",
    "requested_at",
    "sending_at",
    "sent_at",
    "failed_at",
    "responded_at",
    "superseded_at",
}

EXPECTED_UNIQUES = {
    "match_tasks": {"uq_match_tasks_supersedes_id"},
    "match_screening_records": {
        "uq_match_screening_records_task_creator",
        "uq_match_screening_records_task_order",
    },
    "match_candidate_inputs": {"uq_match_candidate_inputs_task_creator"},
    "match_pairwise_records": {"uq_match_pairwise_records_task_creator"},
    "match_result_items": {
        "uq_match_result_items_task_creator",
        "uq_match_result_items_task_backend_order",
    },
    "outreach_campaigns": {"uq_outreach_campaigns_match_task"},
    "templates": {"uq_templates_name_version"},
    "send_batches": {"uq_send_batches_id_campaign"},
    "deliveries": {
        "uq_deliveries_id_campaign_creator",
        "uq_deliveries_batch_creator",
        "uq_deliveries_response_token_digest",
    },
    "campaign_creator_responses": {"uq_campaign_creator_responses_campaign_creator"},
}

EXPECTED_PARTIAL_UNIQUE_INDEXES = {
    "templates": {"uq_templates_default"},
    "deliveries": {"uq_deliveries_current_campaign_creator"},
}

EXPECTED_CHECKS = {
    "shared_settings": {
        "ck_shared_settings_recommended_match_threshold",
        "ck_shared_settings_smtp_rate_per_minute",
    },
    "match_tasks": {
        "ck_match_tasks_status",
        "ck_match_tasks_stage",
        "ck_match_tasks_threshold",
        "ck_match_tasks_completed_units_nonnegative",
        "ck_match_tasks_total_units_nonnegative",
        "ck_match_tasks_result_count_nonnegative",
        "ck_match_tasks_completed_not_above_total",
        "ck_match_tasks_result_not_above_total",
        "ck_match_tasks_error_shape",
        "ck_match_tasks_status_shape",
        "ck_match_tasks_timestamp_shape",
    },
    "match_screening_records": {
        "ck_match_screening_records_order_nonnegative",
        "ck_match_screening_records_expiry",
    },
    "match_candidate_inputs": {"ck_match_candidate_inputs_expiry"},
    "match_pairwise_records": {
        "ck_match_pairwise_records_state",
        "ck_match_pairwise_records_attempt_count",
        "ck_match_pairwise_records_error_shape",
        "ck_match_pairwise_records_state_shape",
        "ck_match_pairwise_records_timestamp_shape",
    },
    "match_result_items": {
        "ck_match_result_items_backend_order",
        "ck_match_result_items_total_score",
        "ck_match_result_items_group",
        "ck_match_result_items_label",
    },
    "templates": {"ck_templates_version"},
    "send_batches": {
        "ck_send_batches_state",
        "ck_send_batches_requested_creator_ids_array",
    },
    "deliveries": {
        "ck_deliveries_template_version",
        "ck_deliveries_send_state",
        "ck_deliveries_response_state",
        "ck_deliveries_response_token_digest",
        "ck_deliveries_smtp_error_shape",
        "ck_deliveries_send_state_shape",
        "ck_deliveries_response_state_shape",
        "ck_deliveries_timestamp_shape",
    },
    "campaign_creator_responses": {
        "ck_campaign_creator_responses_state",
        "ck_campaign_creator_responses_state_shape",
    },
}


def test_match_and_outreach_revision_is_the_single_linear_head(alembic_config) -> None:
    script = ScriptDirectory.from_config(alembic_config)

    assert script.get_heads() == ["20260908_0008"]
    revision = script.get_revision("20260902_0005")
    assert revision is not None
    assert revision.down_revision == "20260902_0004"


def test_match_and_outreach_tables_exist(database_inspector: Inspector) -> None:
    names = set(database_inspector.get_table_names())
    assert TASK_ONE_TABLES <= names


def test_columns_types_nullability_defaults_and_forbidden_fields(
    database_inspector: Inspector,
) -> None:
    forbidden = {
        "response_token",
        "raw_response_token",
        "smtp_password",
        "delivered_at",
        "opened_at",
        "open_count",
        "bounced_at",
        "bounce_reason",
        "mailbox_message_id",
        "rank",
        "expires_at",
    }
    required_defaults = {
        ("match_tasks", "status"),
        ("match_tasks", "stage"),
        ("match_tasks", "completed_units"),
        ("match_tasks", "total_units"),
        ("match_tasks", "result_count"),
        ("match_tasks", "retryable"),
        ("match_pairwise_records", "state"),
        ("match_pairwise_records", "attempt_count"),
        ("match_pairwise_records", "retryable"),
        ("templates", "version"),
        ("templates", "is_default"),
        ("send_batches", "state"),
        ("deliveries", "send_state"),
        ("deliveries", "response_state"),
        ("deliveries", "smtp_retryable"),
        ("campaign_creator_responses", "state"),
    }

    for table_name, expected_names in EXPECTED_COLUMNS.items():
        columns = {
            column["name"]: column
            for column in database_inspector.get_columns(table_name)
        }
        assert set(columns) == expected_names
        assert isinstance(columns["id"]["type"], PGUUID)
        assert columns["id"]["nullable"] is False
        for column_name, column in columns.items():
            if (table_name, column_name) in JSON_COLUMNS:
                assert isinstance(column["type"], JSONB)
            if column_name in TIMESTAMP_COLUMNS:
                assert isinstance(column["type"], DateTime)
                assert column["type"].timezone is True
            if (table_name, column_name) in required_defaults:
                assert column["default"] is not None

        disallowed = forbidden & set(columns)
        if table_name in {"match_screening_records", "match_candidate_inputs"}:
            disallowed.discard("expires_at")
        assert not disallowed


def test_model_metadata_matches_migrated_task_one_schema(
    database_inspector: Inspector,
) -> None:
    assert TASK_ONE_TABLES <= set(Base.metadata.tables)

    for table_name in TASK_ONE_TABLES:
        reflected = {
            column["name"]: column
            for column in database_inspector.get_columns(table_name)
        }
        modeled = Base.metadata.tables[table_name].columns
        assert set(reflected) == set(modeled.keys())
        for name, database_column in reflected.items():
            model_column = modeled[name]
            assert database_column["nullable"] == model_column.nullable
            if isinstance(database_column["type"], DateTime):
                assert database_column["type"].timezone == model_column.type.timezone


def test_foreign_keys_uniques_indexes_and_checks_are_explicit(
    database_inspector: Inspector,
) -> None:
    expected_foreign_keys = {
        "match_tasks": {
            (("game_id",), "game_profiles", ("id",), "RESTRICT"),
            (("supersedes_id",), "match_tasks", ("id",), "RESTRICT"),
        },
        "match_screening_records": {
            (("match_task_id",), "match_tasks", ("id",), "CASCADE"),
            (("creator_id",), "creator_profiles", ("id",), "RESTRICT"),
        },
        "match_candidate_inputs": {
            (("match_task_id",), "match_tasks", ("id",), "CASCADE"),
            (("creator_id",), "creator_profiles", ("id",), "RESTRICT"),
            (
                ("match_task_id", "creator_id"),
                "match_screening_records",
                ("match_task_id", "creator_id"),
                "CASCADE",
            ),
        },
        "match_pairwise_records": {
            (("match_task_id",), "match_tasks", ("id",), "CASCADE"),
            (("creator_id",), "creator_profiles", ("id",), "RESTRICT"),
            (
                ("match_task_id", "creator_id"),
                "match_candidate_inputs",
                ("match_task_id", "creator_id"),
                "CASCADE",
            ),
        },
        "match_result_items": {
            (("match_task_id",), "match_tasks", ("id",), "CASCADE"),
            (("creator_id",), "creator_profiles", ("id",), "RESTRICT"),
            (
                ("match_task_id", "creator_id"),
                "match_pairwise_records",
                ("match_task_id", "creator_id"),
                "CASCADE",
            ),
        },
        "outreach_campaigns": {(("match_task_id",), "match_tasks", ("id",), "CASCADE")},
        "send_batches": {
            (("campaign_id",), "outreach_campaigns", ("id",), "CASCADE"),
            (("template_id",), "templates", ("id",), "SET NULL"),
        },
        "deliveries": {
            (("campaign_id",), "outreach_campaigns", ("id",), "CASCADE"),
            (
                ("send_batch_id", "campaign_id"),
                "send_batches",
                ("id", "campaign_id"),
                "CASCADE",
            ),
            (("creator_id",), "creator_profiles", ("id",), "RESTRICT"),
            (("resends_delivery_id",), "deliveries", ("id",), "RESTRICT"),
        },
        "campaign_creator_responses": {
            (("campaign_id",), "outreach_campaigns", ("id",), "CASCADE"),
            (("creator_id",), "creator_profiles", ("id",), "RESTRICT"),
            (
                ("final_delivery_id", "campaign_id", "creator_id"),
                "deliveries",
                ("id", "campaign_id", "creator_id"),
                "RESTRICT",
            ),
        },
    }

    for table_name, expected in expected_foreign_keys.items():
        actual = {
            (
                tuple(foreign_key["constrained_columns"]),
                foreign_key["referred_table"],
                tuple(foreign_key["referred_columns"]),
                foreign_key.get("options", {}).get("ondelete", "NO ACTION"),
            )
            for foreign_key in database_inspector.get_foreign_keys(table_name)
        }
        assert actual == expected

    for table_name, expected in EXPECTED_UNIQUES.items():
        actual = {
            unique["name"]
            for unique in database_inspector.get_unique_constraints(table_name)
        }
        assert expected <= actual

    for table_name, expected in EXPECTED_PARTIAL_UNIQUE_INDEXES.items():
        indexes = {
            index["name"]: index for index in database_inspector.get_indexes(table_name)
        }
        assert expected <= set(indexes)
        for index_name in expected:
            assert indexes[index_name]["unique"] is True
            assert indexes[index_name]["dialect_options"]["postgresql_where"]

    for table_name, expected in EXPECTED_CHECKS.items():
        actual = {
            check["name"]
            for check in database_inspector.get_check_constraints(table_name)
        }
        assert expected <= actual


def test_match_uniqueness_and_publication_constraints(session: Session) -> None:
    flow = _insert_complete_match_flow(session.connection())

    duplicate_cases = [
        (
            """
            INSERT INTO match_screening_records (
                id, match_task_id, creator_id, screening_order,
                locked_creator_brief, selected, expires_at
            ) VALUES (
                :id, :match_task_id, :creator_id, 1,
                '{}'::jsonb, true, :expires_at
            )
            """,
            "uq_match_screening_records_task_creator",
        ),
        (
            """
            INSERT INTO match_candidate_inputs (
                id, match_task_id, creator_id, expires_at
            ) VALUES (:id, :match_task_id, :creator_id, :expires_at)
            """,
            "uq_match_candidate_inputs_task_creator",
        ),
        (
            """
            INSERT INTO match_pairwise_records (
                id, match_task_id, creator_id, state, attempt_count,
                match_brief, started_at, completed_at
            ) VALUES (
                :id, :match_task_id, :creator_id, 'succeeded', 1,
                '{}'::jsonb, :started_at, :completed_at
            )
            """,
            "uq_match_pairwise_records_task_creator",
        ),
        (
            """
            INSERT INTO match_result_items (
                id, match_task_id, creator_id, backend_order, match_brief,
                total_score, dimension_scores, dimension_outcomes,
                match_reasons, result_group, qualitative_label
            ) VALUES (
                :id, :match_task_id, :creator_id, 1, '{}'::jsonb,
                0.75, '{}'::jsonb, '{}'::jsonb, '[]'::jsonb,
                'recommended', 'Good Match'
            )
            """,
            "uq_match_result_items_task_creator",
        ),
    ]
    common = {
        "match_task_id": flow["match_task_id"],
        "creator_id": flow["creator_id"],
        "expires_at": datetime.now(UTC) + timedelta(days=30),
        "started_at": datetime.now(UTC),
        "completed_at": datetime.now(UTC),
    }
    for statement, constraint_name in duplicate_cases:
        _assert_constraint(
            session,
            statement,
            {"id": uuid4(), **common},
            constraint_name,
        )

    second_creator = _insert_creator(session.connection(), "second-result-order")
    _insert_selected_pair(
        session.connection(), flow["match_task_id"], second_creator, screening_order=1
    )
    _assert_constraint(
        session,
        """
        INSERT INTO match_result_items (
            id, match_task_id, creator_id, backend_order, match_brief,
            total_score, dimension_scores, dimension_outcomes, match_reasons,
            result_group, qualitative_label
        ) VALUES (
            :id, :match_task_id, :creator_id, 0, '{}'::jsonb,
            0.75, '{}'::jsonb, '{}'::jsonb, '[]'::jsonb,
            'recommended', 'Good Match'
        )
        """,
        {
            "id": uuid4(),
            "match_task_id": flow["match_task_id"],
            "creator_id": second_creator,
        },
        "uq_match_result_items_task_backend_order",
    )


def test_outreach_uniqueness_constraints(session: Session) -> None:
    flow = _insert_outreach_flow(session.connection())

    _assert_constraint(
        session,
        "INSERT INTO outreach_campaigns (id, match_task_id) VALUES (:id, :match_task_id)",
        {"id": uuid4(), "match_task_id": flow["match_task_id"]},
        "uq_outreach_campaigns_match_task",
    )
    _assert_constraint(
        session,
        """
        INSERT INTO templates (
            id, name, version, subject_template, body_markdown,
            accepted_label, declined_label, is_default
        ) VALUES (
            :id, 'Second Default', 1, 'Subject', 'Body',
            'Accept', 'Decline', true
        )
        """,
        {"id": uuid4()},
        "uq_templates_default",
    )
    _assert_constraint(
        session,
        """
        INSERT INTO deliveries (
            id, campaign_id, send_batch_id, creator_id, recipient_email,
            rendered_subject, rendered_markdown, rendered_html,
            template_name, template_version, accepted_label, declined_label,
            sender_name, sender_address, reply_to, response_token_digest
        ) VALUES (
            :id, :campaign_id, :send_batch_id, :creator_id,
            'creator@example.com', 'Subject', 'Body', '<p>Body</p>',
            'Default', 1, 'Accept', 'Decline', 'Sender',
            'sender@example.com', 'reply@example.com', :digest
        )
        """,
        {
            "id": uuid4(),
            "campaign_id": flow["campaign_id"],
            "send_batch_id": flow["send_batch_id"],
            "creator_id": flow["creator_id"],
            "digest": "b" * 64,
        },
        "uq_deliveries_batch_creator",
    )

    second_batch_id = _insert_send_batch(session.connection(), flow["campaign_id"])
    _assert_constraint(
        session,
        """
        INSERT INTO deliveries (
            id, campaign_id, send_batch_id, creator_id, recipient_email,
            rendered_subject, rendered_markdown, rendered_html,
            template_name, template_version, accepted_label, declined_label,
            sender_name, sender_address, reply_to, response_token_digest
        ) VALUES (
            :id, :campaign_id, :send_batch_id, :creator_id,
            'creator@example.com', 'Subject', 'Body', '<p>Body</p>',
            'Default', 1, 'Accept', 'Decline', 'Sender',
            'sender@example.com', 'reply@example.com', :digest
        )
        """,
        {
            "id": uuid4(),
            "campaign_id": flow["campaign_id"],
            "send_batch_id": second_batch_id,
            "creator_id": flow["creator_id"],
            "digest": "c" * 64,
        },
        "uq_deliveries_current_campaign_creator",
    )
    _assert_constraint(
        session,
        """
        INSERT INTO campaign_creator_responses (
            id, campaign_id, creator_id
        ) VALUES (:id, :campaign_id, :creator_id)
        """,
        {
            "id": uuid4(),
            "campaign_id": flow["campaign_id"],
            "creator_id": flow["creator_id"],
        },
        "uq_campaign_creator_responses_campaign_creator",
    )

    second_match = _insert_complete_match_flow(session.connection())
    second_campaign = _insert_campaign(
        session.connection(), second_match["match_task_id"]
    )
    second_batch = _insert_send_batch(session.connection(), second_campaign)
    _assert_constraint(
        session,
        """
        INSERT INTO deliveries (
            id, campaign_id, send_batch_id, creator_id, recipient_email,
            rendered_subject, rendered_markdown, rendered_html,
            template_name, template_version, accepted_label, declined_label,
            sender_name, sender_address, reply_to, response_token_digest
        ) VALUES (
            :id, :campaign_id, :send_batch_id, :creator_id,
            'other@example.com', 'Subject', 'Body', '<p>Body</p>',
            'Default', 1, 'Accept', 'Decline', 'Sender',
            'sender@example.com', 'reply@example.com', :digest
        )
        """,
        {
            "id": uuid4(),
            "campaign_id": second_campaign,
            "send_batch_id": second_batch,
            "creator_id": second_match["creator_id"],
            "digest": "a" * 64,
        },
        "uq_deliveries_response_token_digest",
    )


def test_delivery_represents_token_neutral_html_with_only_capability_digest(
    session: Session,
) -> None:
    flow = _insert_outreach_flow(session.connection())
    raw_capability = "raw-capability-must-never-be-persisted"
    digest = sha256(raw_capability.encode()).hexdigest()
    token_neutral_html = (
        '<p>Body</p><div data-fmg-response-cta="accepted"></div>'
        '<div data-fmg-response-cta="declined"></div>'
    )
    session.execute(
        text(
            """
            UPDATE deliveries
            SET rendered_html = :rendered_html,
                response_token_digest = :response_token_digest
            WHERE id = :delivery_id
            """
        ),
        {
            "delivery_id": flow["delivery_id"],
            "rendered_html": token_neutral_html,
            "response_token_digest": digest,
        },
    )

    saved = session.execute(
        text(
            """
            SELECT rendered_html, response_token_digest
            FROM deliveries
            WHERE id = :delivery_id
            """
        ),
        {"delivery_id": flow["delivery_id"]},
    ).one()
    assert saved.rendered_html == token_neutral_html
    assert saved.response_token_digest == digest
    assert raw_capability not in saved.rendered_html
    assert raw_capability != saved.response_token_digest


@pytest.mark.parametrize(
    ("statement", "parameters", "constraint_name"),
    [
        (
            "UPDATE shared_settings SET recommended_match_threshold = 1.01",
            {},
            "ck_shared_settings_recommended_match_threshold",
        ),
        (
            "UPDATE shared_settings SET smtp_rate_per_minute = 0",
            {},
            "ck_shared_settings_smtp_rate_per_minute",
        ),
        (
            "UPDATE match_tasks SET completed_units = -1 WHERE id = :match_task_id",
            {"match_task_id": "match_task_id"},
            "ck_match_tasks_completed_units_nonnegative",
        ),
        (
            "UPDATE match_tasks SET total_units = 0, completed_units = 1 WHERE id = :match_task_id",
            {"match_task_id": "match_task_id"},
            "ck_match_tasks_completed_not_above_total",
        ),
        (
            "UPDATE match_tasks SET status = 'unknown' WHERE id = :match_task_id",
            {"match_task_id": "match_task_id"},
            "ck_match_tasks_status",
        ),
        (
            "UPDATE match_tasks SET stage = 'unknown' WHERE id = :match_task_id",
            {"match_task_id": "match_task_id"},
            "ck_match_tasks_stage",
        ),
        (
            "UPDATE match_result_items SET total_score = 1.01 WHERE id = :result_id",
            {"result_id": "result_id"},
            "ck_match_result_items_total_score",
        ),
        (
            "UPDATE match_result_items SET result_group = 'maybe' WHERE id = :result_id",
            {"result_id": "result_id"},
            "ck_match_result_items_group",
        ),
        (
            "UPDATE templates SET version = 0 WHERE id = :template_id",
            {"template_id": "template_id"},
            "ck_templates_version",
        ),
        (
            "UPDATE send_batches SET state = 'unknown' WHERE id = :send_batch_id",
            {"send_batch_id": "send_batch_id"},
            "ck_send_batches_state",
        ),
        (
            "UPDATE deliveries SET response_token_digest = 'RAW-TOKEN' WHERE id = :delivery_id",
            {"delivery_id": "delivery_id"},
            "ck_deliveries_response_token_digest",
        ),
        (
            "UPDATE deliveries SET send_state = 'delivered' WHERE id = :delivery_id",
            {"delivery_id": "delivery_id"},
            "ck_deliveries_send_state",
        ),
        (
            "UPDATE deliveries SET response_state = 'maybe' WHERE id = :delivery_id",
            {"delivery_id": "delivery_id"},
            "ck_deliveries_response_state",
        ),
        (
            "UPDATE campaign_creator_responses SET state = 'maybe' WHERE id = :response_id",
            {"response_id": "response_id"},
            "ck_campaign_creator_responses_state",
        ),
    ],
)
def test_numeric_enum_and_digest_checks_are_enforced(
    session: Session,
    statement: str,
    parameters: dict[str, object],
    constraint_name: str,
) -> None:
    flow = _insert_outreach_flow(session.connection())
    resolved = {
        key: flow[value] if isinstance(value, str) and value in flow else value
        for key, value in parameters.items()
    }
    _assert_constraint(session, statement, resolved, constraint_name)


@pytest.mark.parametrize(
    ("statement", "constraint_name"),
    [
        (
            "UPDATE match_tasks SET status = 'failed' WHERE id = :match_task_id",
            "ck_match_tasks_status_shape",
        ),
        (
            "UPDATE match_pairwise_records SET match_brief = NULL WHERE id = :pairwise_id",
            "ck_match_pairwise_records_state_shape",
        ),
        (
            "UPDATE deliveries SET response_state = 'accepted' WHERE id = :delivery_id",
            "ck_deliveries_response_state_shape",
        ),
        (
            "UPDATE campaign_creator_responses SET state = 'accepted' WHERE id = :response_id",
            "ck_campaign_creator_responses_state_shape",
        ),
    ],
)
def test_ordinary_state_shape_checks_are_enforced(
    session: Session, statement: str, constraint_name: str
) -> None:
    flow = _insert_outreach_flow(session.connection())
    _assert_constraint(session, statement, flow, constraint_name)


def test_failed_match_can_be_superseded_without_erasing_safe_failure(
    session: Session,
) -> None:
    game_id = _insert_game(session.connection(), "Superseded Match")
    match_task_id = _insert_match_task(session.connection(), game_id)
    terminal_at = datetime.now(UTC)
    session.execute(
        text(
            """
            UPDATE match_tasks
            SET status = 'failed',
                error_code = 'match_temporarily_unavailable',
                error_message = 'Match is temporarily unavailable. Please retry.',
                retryable = true,
                completed_at = :terminal_at
            WHERE id = :match_task_id
            """
        ),
        {"match_task_id": match_task_id, "terminal_at": terminal_at},
    )

    session.execute(
        text(
            """
            UPDATE match_tasks
            SET status = 'superseded', retryable = false
            WHERE id = :match_task_id
            """
        ),
        {"match_task_id": match_task_id},
    )

    saved = session.execute(
        text(
            """
            SELECT status, error_code, error_message, retryable
            FROM match_tasks
            WHERE id = :match_task_id
            """
        ),
        {"match_task_id": match_task_id},
    ).one()
    assert saved == (
        "superseded",
        "match_temporarily_unavailable",
        "Match is temporarily unavailable. Please retry.",
        False,
    )


def test_pair_identity_foreign_keys_and_history_delete_behavior(
    session: Session,
) -> None:
    flow = _insert_outreach_flow(session.connection())

    unrelated_creator = _insert_creator(session.connection(), "unrelated-pair")
    _assert_constraint(
        session,
        """
        INSERT INTO match_candidate_inputs (
            id, match_task_id, creator_id, expires_at
        ) VALUES (:id, :match_task_id, :creator_id, :expires_at)
        """,
        {
            "id": uuid4(),
            "match_task_id": flow["match_task_id"],
            "creator_id": unrelated_creator,
            "expires_at": datetime.now(UTC) + timedelta(days=30),
        },
        "fk_match_candidate_inputs_screening_pair",
    )
    _assert_constraint(
        session,
        "DELETE FROM creator_profiles WHERE id = :creator_id",
        {"creator_id": flow["creator_id"]},
        "fk_match_screening_records_creator",
    )
    _assert_constraint(
        session,
        "DELETE FROM game_profiles WHERE id = :game_id",
        {"game_id": flow["game_id"]},
        "fk_match_tasks_game",
    )

    session.execute(
        text("DELETE FROM match_tasks WHERE id = :match_task_id"),
        {"match_task_id": flow["match_task_id"]},
    )
    for table_name in TASK_ONE_TABLES - {"templates"}:
        assert session.scalar(text(f"SELECT count(*) FROM {table_name}")) == 0
    assert (
        session.scalar(
            text("SELECT count(*) FROM creator_profiles WHERE id = :creator_id"),
            {"creator_id": flow["creator_id"]},
        )
        == 1
    )
    assert (
        session.scalar(
            text("SELECT count(*) FROM game_profiles WHERE id = :game_id"),
            {"game_id": flow["game_id"]},
        )
        == 1
    )


def test_fresh_base_to_0005_upgrade_and_downgrade_removal(
    migrated_database: None, alembic_config, database_engine
) -> None:
    try:
        command.downgrade(alembic_config, "base")
        command.upgrade(alembic_config, "20260902_0005")
        assert TASK_ONE_TABLES <= set(inspect(database_engine).get_table_names())

        command.downgrade(alembic_config, "20260902_0004")
        assert TASK_ONE_TABLES.isdisjoint(inspect(database_engine).get_table_names())

        command.upgrade(alembic_config, "20260902_0005")
        assert TASK_ONE_TABLES <= set(inspect(database_engine).get_table_names())
    finally:
        command.upgrade(alembic_config, "head")


def test_0004_upgrade_downgrade_reupgrade_preserves_existing_business_rows(
    migrated_database: None, alembic_config, database_engine
) -> None:
    game_id = uuid4()
    creator_id = uuid4()
    contact_id = uuid4()
    job_id = uuid4()
    secret_id = uuid4()
    idempotency_id = uuid4()
    suffix = uuid4().hex
    try:
        command.downgrade(alembic_config, "20260902_0004")
        with database_engine.begin() as connection:
            _insert_profile_rows(connection, game_id, creator_id, suffix)
            connection.execute(
                text(
                    """
                    INSERT INTO creator_contacts (
                        id, creator_id, email, source_type, is_manual, is_active
                    ) VALUES (
                        :id, :creator_id, 'preserved@example.com',
                        'manual', true, true
                    )
                    """
                ),
                {"id": contact_id, "creator_id": creator_id},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO analysis_jobs (
                        id, target_type, canonical_target_id, canonical_url,
                        mode, status, completed_units, total_units, retryable
                    ) VALUES (
                        :id, 'game', :target_id, :canonical_url,
                        'create', 'queued', 0, 0, false
                    )
                    """
                ),
                {
                    "id": job_id,
                    "target_id": f"preserved-{suffix}",
                    "canonical_url": f"https://example.com/jobs/{suffix}",
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO service_secrets (
                        id, service, ciphertext, nonce
                    ) VALUES (:id, :service, :ciphertext, :nonce)
                    """
                ),
                {
                    "id": secret_id,
                    "service": f"preserved-{suffix}",
                    "ciphertext": b"ciphertext",
                    "nonce": b"nonce",
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO idempotency_records (
                        id, key, request_hash, method, path,
                        response_status, response_body
                    ) VALUES (
                        :id, :key, :request_hash, 'POST', '/preserved',
                        202, '{}'::jsonb
                    )
                    """
                ),
                {
                    "id": idempotency_id,
                    "key": f"preserved-{suffix}",
                    "request_hash": "f" * 64,
                },
            )
            connection.execute(
                text(
                    """
                    UPDATE shared_settings
                    SET recommended_match_threshold = 0.65,
                        smtp_rate_per_minute = 17
                    """
                )
            )

        command.upgrade(alembic_config, "20260902_0005")
        with database_engine.connect() as connection:
            _assert_preserved_rows(
                connection,
                game_id,
                creator_id,
                contact_id,
                job_id,
                secret_id,
                idempotency_id,
            )
        command.downgrade(alembic_config, "20260902_0004")
        with database_engine.connect() as connection:
            _assert_preserved_rows(
                connection,
                game_id,
                creator_id,
                contact_id,
                job_id,
                secret_id,
                idempotency_id,
            )
        command.upgrade(alembic_config, "20260902_0005")
        with database_engine.connect() as connection:
            _assert_preserved_rows(
                connection,
                game_id,
                creator_id,
                contact_id,
                job_id,
                secret_id,
                idempotency_id,
            )
    finally:
        command.upgrade(alembic_config, "head")
        with database_engine.begin() as connection:
            connection.execute(
                text("DELETE FROM analysis_jobs WHERE id = :id"), {"id": job_id}
            )
            connection.execute(
                text("DELETE FROM creator_contacts WHERE id = :id"),
                {"id": contact_id},
            )
            connection.execute(
                text("DELETE FROM game_profiles WHERE id = :id"), {"id": game_id}
            )
            connection.execute(
                text("DELETE FROM creator_profiles WHERE id = :id"),
                {"id": creator_id},
            )
            connection.execute(
                text("DELETE FROM service_secrets WHERE id = :id"),
                {"id": secret_id},
            )
            connection.execute(
                text("DELETE FROM idempotency_records WHERE id = :id"),
                {"id": idempotency_id},
            )
            connection.execute(
                text(
                    """
                    UPDATE shared_settings
                    SET recommended_match_threshold = 0.70,
                        smtp_rate_per_minute = 10
                    """
                )
            )


def _assert_constraint(
    session: Session,
    statement: str,
    parameters: dict[str, object],
    constraint_name: str,
) -> None:
    savepoint = session.begin_nested()
    try:
        with pytest.raises(IntegrityError) as error:
            session.execute(text(statement), parameters)
        assert error.value.orig.diag.constraint_name == constraint_name
    finally:
        savepoint.rollback()


def _insert_creator(connection: Connection, label: str) -> UUID:
    creator_id = uuid4()
    suffix = uuid4().hex
    connection.execute(
        text(
            """
            INSERT INTO creator_profiles (
                id, youtube_channel_id, canonical_url, sort_name,
                current_facts, analysis, brief, source_status,
                model_metadata, prompt_metadata
            ) VALUES (
                :id, :channel_id, :canonical_url, :sort_name,
                '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb,
                '{}'::jsonb, '{}'::jsonb
            )
            """
        ),
        {
            "id": creator_id,
            "channel_id": f"UC{suffix}",
            "canonical_url": f"https://www.youtube.com/channel/UC{suffix}",
            "sort_name": label,
        },
    )
    return creator_id


def _insert_game(connection: Connection, label: str) -> UUID:
    game_id = uuid4()
    suffix = uuid4().hex
    connection.execute(
        text(
            """
            INSERT INTO game_profiles (
                id, steam_app_id, canonical_url, sort_name,
                current_facts, analysis, brief, source_status,
                model_metadata, prompt_metadata
            ) VALUES (
                :id, :steam_app_id, :canonical_url, :sort_name,
                '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb,
                '{}'::jsonb, '{}'::jsonb
            )
            """
        ),
        {
            "id": game_id,
            "steam_app_id": suffix[:16],
            "canonical_url": f"https://store.steampowered.com/app/{suffix[:16]}",
            "sort_name": label,
        },
    )
    return game_id


def _insert_match_task(connection: Connection, game_id: UUID) -> UUID:
    match_task_id = uuid4()
    connection.execute(
        text(
            """
            INSERT INTO match_tasks (
                id, game_id, locked_game_brief, shuffle_seed,
                recommended_match_threshold, input_expires_at
            ) VALUES (
                :id, :game_id, '{}'::jsonb, 42, 0.70, :input_expires_at
            )
            """
        ),
        {
            "id": match_task_id,
            "game_id": game_id,
            "input_expires_at": datetime.now(UTC) + timedelta(days=30),
        },
    )
    return match_task_id


def _insert_selected_pair(
    connection: Connection,
    match_task_id: UUID,
    creator_id: UUID,
    screening_order: int = 0,
) -> dict[str, UUID]:
    now = datetime.now(UTC)
    expires_at = now + timedelta(days=30)
    screening_id = uuid4()
    candidate_id = uuid4()
    pairwise_id = uuid4()
    connection.execute(
        text(
            """
            INSERT INTO match_screening_records (
                id, match_task_id, creator_id, screening_order,
                locked_creator_brief, selected, expires_at
            ) VALUES (
                :id, :match_task_id, :creator_id, :screening_order,
                '{}'::jsonb, true, :expires_at
            )
            """
        ),
        {
            "id": screening_id,
            "match_task_id": match_task_id,
            "creator_id": creator_id,
            "screening_order": screening_order,
            "expires_at": expires_at,
        },
    )
    connection.execute(
        text(
            """
            INSERT INTO match_candidate_inputs (
                id, match_task_id, creator_id, locked_creator_profile,
                input_model_metadata, input_prompt_metadata, expires_at
            ) VALUES (
                :id, :match_task_id, :creator_id, '{}'::jsonb,
                '{}'::jsonb, '{}'::jsonb, :expires_at
            )
            """
        ),
        {
            "id": candidate_id,
            "match_task_id": match_task_id,
            "creator_id": creator_id,
            "expires_at": expires_at,
        },
    )
    connection.execute(
        text(
            """
            INSERT INTO match_pairwise_records (
                id, match_task_id, creator_id, state, attempt_count,
                match_brief, started_at, completed_at
            ) VALUES (
                :id, :match_task_id, :creator_id, 'succeeded', 1,
                '{}'::jsonb, :started_at, :completed_at
            )
            """
        ),
        {
            "id": pairwise_id,
            "match_task_id": match_task_id,
            "creator_id": creator_id,
            "started_at": now,
            "completed_at": now,
        },
    )
    return {
        "screening_id": screening_id,
        "candidate_id": candidate_id,
        "pairwise_id": pairwise_id,
    }


def _insert_complete_match_flow(connection: Connection) -> dict[str, UUID]:
    game_id = _insert_game(connection, "Migration Game")
    creator_id = _insert_creator(connection, "Migration Creator")
    match_task_id = _insert_match_task(connection, game_id)
    pair = _insert_selected_pair(connection, match_task_id, creator_id)
    result_id = uuid4()
    connection.execute(
        text(
            """
            INSERT INTO match_result_items (
                id, match_task_id, creator_id, backend_order, match_brief,
                total_score, dimension_scores, dimension_outcomes,
                match_reasons, result_group, qualitative_label
            ) VALUES (
                :id, :match_task_id, :creator_id, 0, '{}'::jsonb,
                0.75, '{}'::jsonb, '{}'::jsonb, '[]'::jsonb,
                'recommended', 'Good Match'
            )
            """
        ),
        {
            "id": result_id,
            "match_task_id": match_task_id,
            "creator_id": creator_id,
        },
    )
    return {
        "game_id": game_id,
        "creator_id": creator_id,
        "match_task_id": match_task_id,
        "result_id": result_id,
        **pair,
    }


def _insert_campaign(connection: Connection, match_task_id: UUID) -> UUID:
    campaign_id = uuid4()
    connection.execute(
        text(
            "INSERT INTO outreach_campaigns (id, match_task_id) VALUES (:id, :match_task_id)"
        ),
        {"id": campaign_id, "match_task_id": match_task_id},
    )
    return campaign_id


def _insert_send_batch(connection: Connection, campaign_id: UUID) -> UUID:
    send_batch_id = uuid4()
    connection.execute(
        text(
            """
            INSERT INTO send_batches (
                id, campaign_id, requested_creator_ids
            ) VALUES (:id, :campaign_id, '[]'::jsonb)
            """
        ),
        {"id": send_batch_id, "campaign_id": campaign_id},
    )
    return send_batch_id


def _insert_outreach_flow(connection: Connection) -> dict[str, UUID]:
    flow = _insert_complete_match_flow(connection)
    campaign_id = _insert_campaign(connection, flow["match_task_id"])
    template_id = uuid4()
    connection.execute(
        text(
            """
            INSERT INTO templates (
                id, name, version, subject_template, body_markdown,
                accepted_label, declined_label, is_default
            ) VALUES (
                :id, 'Default', 1, 'Subject', 'Body',
                'Accept', 'Decline', true
            )
            """
        ),
        {"id": template_id},
    )
    send_batch_id = uuid4()
    connection.execute(
        text(
            """
            INSERT INTO send_batches (
                id, campaign_id, template_id, requested_creator_ids
            ) VALUES (:id, :campaign_id, :template_id, '[]'::jsonb)
            """
        ),
        {
            "id": send_batch_id,
            "campaign_id": campaign_id,
            "template_id": template_id,
        },
    )
    delivery_id = uuid4()
    connection.execute(
        text(
            """
            INSERT INTO deliveries (
                id, campaign_id, send_batch_id, creator_id, recipient_email,
                rendered_subject, rendered_markdown, rendered_html,
                template_name, template_version, accepted_label, declined_label,
                sender_name, sender_address, reply_to, response_token_digest
            ) VALUES (
                :id, :campaign_id, :send_batch_id, :creator_id,
                'creator@example.com', 'Subject', 'Body', '<p>Body</p>',
                'Default', 1, 'Accept', 'Decline', 'Sender',
                'sender@example.com', 'reply@example.com', :digest
            )
            """
        ),
        {
            "id": delivery_id,
            "campaign_id": campaign_id,
            "send_batch_id": send_batch_id,
            "creator_id": flow["creator_id"],
            "digest": "a" * 64,
        },
    )
    response_id = uuid4()
    connection.execute(
        text(
            """
            INSERT INTO campaign_creator_responses (
                id, campaign_id, creator_id
            ) VALUES (:id, :campaign_id, :creator_id)
            """
        ),
        {
            "id": response_id,
            "campaign_id": campaign_id,
            "creator_id": flow["creator_id"],
        },
    )
    return {
        **flow,
        "campaign_id": campaign_id,
        "template_id": template_id,
        "send_batch_id": send_batch_id,
        "delivery_id": delivery_id,
        "response_id": response_id,
    }


def _insert_profile_rows(
    connection: Connection,
    game_id: UUID,
    creator_id: UUID,
    suffix: str,
) -> None:
    connection.execute(
        text(
            """
            INSERT INTO game_profiles (
                id, steam_app_id, canonical_url, sort_name, current_facts,
                analysis, brief, source_status, model_metadata, prompt_metadata
            ) VALUES (
                :id, :steam_app_id, :canonical_url, 'Preserved Game',
                '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb,
                '{}'::jsonb, '{}'::jsonb
            )
            """
        ),
        {
            "id": game_id,
            "steam_app_id": suffix[:16],
            "canonical_url": f"https://store.steampowered.com/app/{suffix[:16]}",
        },
    )
    connection.execute(
        text(
            """
            INSERT INTO creator_profiles (
                id, youtube_channel_id, canonical_url, sort_name, current_facts,
                analysis, brief, source_status, model_metadata, prompt_metadata
            ) VALUES (
                :id, :channel_id, :canonical_url, 'Preserved Creator',
                '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb,
                '{}'::jsonb, '{}'::jsonb
            )
            """
        ),
        {
            "id": creator_id,
            "channel_id": f"UC{suffix}",
            "canonical_url": f"https://www.youtube.com/channel/UC{suffix}",
        },
    )


def _assert_preserved_rows(
    connection: Connection,
    game_id: UUID,
    creator_id: UUID,
    contact_id: UUID,
    job_id: UUID,
    secret_id: UUID,
    idempotency_id: UUID,
) -> None:
    expected = {
        "game_profiles": game_id,
        "creator_profiles": creator_id,
        "creator_contacts": contact_id,
        "analysis_jobs": job_id,
        "service_secrets": secret_id,
        "idempotency_records": idempotency_id,
    }
    for table_name, row_id in expected.items():
        assert (
            connection.scalar(
                text(f"SELECT count(*) FROM {table_name} WHERE id = :id"),
                {"id": row_id},
            )
            == 1
        )
    settings = connection.execute(
        text(
            """
            SELECT recommended_match_threshold, smtp_rate_per_minute
            FROM shared_settings
            """
        )
    ).one()
    assert settings.recommended_match_threshold == Decimal("0.65")
    assert settings.smtp_rate_per_minute == 17
