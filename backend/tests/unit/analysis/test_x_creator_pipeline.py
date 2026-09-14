from app.analysis.contracts import XCreatorSource, XPostSource
from app.analysis.prompts.x_creator import build_x_creator_bundle


def test_x_prompt_bounds_long_posts_without_losing_evidence_identity():
    source = XCreatorSource(
        platform_account_id="12345",
        canonical_url="https://x.com/i/user/12345",
        title="Example",
        username="example",
        description="A" * 10000,
        posts=tuple(
            XPostSource(
                id=str(i), canonical_url=f"https://x.com/i/status/{i}", text="B" * 30000
            )
            for i in range(1, 51)
        ),
        raw_account={},
        raw_posts={},
    )
    bundle = build_x_creator_bundle(source)
    assert sum(len(message.content) for message in bundle.messages) < 131072
    assert len(bundle.evidence_catalog.entries) == 51
    assert bundle.evidence_catalog.entries[-1].reference == "https://x.com/i/status/50"
    assert all(
        entry.source_type == "public_link" for entry in bundle.evidence_catalog.entries
    )


def test_empty_x_content_is_explicit_and_does_not_invent_video_source():
    source = XCreatorSource(
        platform_account_id="12345",
        canonical_url="https://x.com/i/user/12345",
        title="Example",
        username="example",
        raw_account={},
        raw_posts={},
    )
    bundle = build_x_creator_bundle(source)
    text = "\n".join(message.content for message in bundle.messages)
    assert '"posts":[]' in text or '"posts": []' in text
    assert '"videos"' not in text
    assert '"subscriber_count"' not in text
    assert [entry.reference for entry in bundle.evidence_catalog.entries] == [
        "https://x.com/i/user/12345"
    ]


def test_x_synthesis_prompt_explains_runtime_inference_and_compact_brief_contract():
    # Live X synthesis used source_fact for audience, copied full observation
    # evidence into the compact brief, and emitted more than three list values.
    # These instructions must reach the model in trusted system context.
    from tests.integration.test_x_creator_analysis import source

    bundle = build_x_creator_bundle(source())
    rules = "\n".join(message.content for message in bundle.messages if message.role == "system")
    assert "provenance=ai_inference" in rules
    assert "kind=ai_inference" in rules
    assert "exactly one evidence reference" in rules
    assert "kind, source_type, reference" in rules
    assert "no observation field" in rules
    assert "at most three unique values" in rules
    assert "8000 UTF-8 bytes" in rules
