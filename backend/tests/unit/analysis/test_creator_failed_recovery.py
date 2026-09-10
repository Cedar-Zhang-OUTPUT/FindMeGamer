from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.analysis.creator_recovery import (
    validate_failed_checkpoints,
    CreatorRecoveryError,
)
from app.analysis.creator_map_reduce_pipeline import (
    CreatorSourceCheckpoint,
    CreatorContactCheckpoint,
    SOURCE_NODE_KEY,
    CONTACT_NODE_KEY,
    VISUAL_NODE_KEY,
)
from app.analysis.creator_pipeline import unavailable_visual_analysis
from app.schemas.ai_creator import CreatorContactEvidence
from tests.unit.analysis.test_creator_pipeline import _source
from tests.unit.analysis.test_creator_map_reduce_pipeline import _output_for
from app.schemas.ai_creator_map_reduce import CreatorVideoBatchDigest

NOW = datetime(2026, 9, 10, tzinfo=UTC)


def saved_nodes():
    source = _source()
    payloads = {
        SOURCE_NODE_KEY: CreatorSourceCheckpoint.from_source(source),
        CONTACT_NODE_KEY: CreatorContactCheckpoint(
            evidence=CreatorContactEvidence(candidates=()), status="unavailable"
        ),
        VISUAL_NODE_KEY: unavailable_visual_analysis("No visual evidence."),
        "batch:v1:00": _output_for(CreatorVideoBatchDigest),
    }
    return source, {
        key: SimpleNamespace(
            output_payload=value.model_dump(mode="json"),
            created_at=NOW - timedelta(hours=1),
        )
        for key, value in payloads.items()
    }


def test_partial_successes_are_accepted_without_requiring_failed_nodes():
    source, nodes = saved_nodes()
    assert validate_failed_checkpoints(
        nodes, channel_id=source.channel_id, canonical_url=source.canonical_url, now=NOW
    ) == tuple(sorted(nodes))


@pytest.mark.parametrize(
    "missing", [SOURCE_NODE_KEY, CONTACT_NODE_KEY, VISUAL_NODE_KEY]
)
def test_missing_acquisition_checkpoint_does_not_silently_allow_refetch(missing):
    source, nodes = saved_nodes()
    del nodes[missing]
    with pytest.raises(CreatorRecoveryError, match="search_resume_checkpoint_missing"):
        validate_failed_checkpoints(
            nodes,
            channel_id=source.channel_id,
            canonical_url=source.canonical_url,
            now=NOW,
        )


def test_expired_source_requires_explicit_new_analysis():
    source, nodes = saved_nodes()
    nodes[SOURCE_NODE_KEY].created_at = NOW - timedelta(days=31)
    with pytest.raises(CreatorRecoveryError, match="search_resume_source_expired"):
        validate_failed_checkpoints(
            nodes,
            channel_id=source.channel_id,
            canonical_url=source.canonical_url,
            now=NOW,
        )


def test_wrong_source_identity_is_rejected():
    source, nodes = saved_nodes()
    with pytest.raises(CreatorRecoveryError, match="search_identity_changed"):
        validate_failed_checkpoints(
            nodes, channel_id="UCother123", canonical_url=source.canonical_url, now=NOW
        )


def test_invalid_saved_output_is_not_dropped_or_recomputed():
    source, nodes = saved_nodes()
    nodes["batch:v1:00"].output_payload = {"invalid": "not an output"}
    with pytest.raises(CreatorRecoveryError, match="search_resume_checkpoint_invalid"):
        validate_failed_checkpoints(
            nodes,
            channel_id=source.channel_id,
            canonical_url=source.canonical_url,
            now=NOW,
        )
