"""Canonicalize only exact current-stage intermediate citation identities.

No fuzzy reference matching, inference of a missing source, claim removal or
evidence deletion. The original content and final catalog checks are preserved.
"""

from contextlib import contextmanager
from contextvars import ContextVar
import json

from app.core.analysis_diagnostics import emit, last_model_call_id
from app.schemas.ai_game import EvidenceCatalog

_catalog = ContextVar("current_evidence_catalog", default=None)


@contextmanager
def evidence_bindings(catalog: EvidenceCatalog):
    token = _catalog.set(catalog)
    try:
        yield
    finally:
        _catalog.reset(token)


def normalize_evidence_json(content: str) -> str:
    catalog = _catalog.get()
    if catalog is None:
        return content
    targets = {
        e.reference: e
        for e in catalog.entries
        if e.source_type == "intermediate_output"
        and e.allowed_kinds == ("ai_inference",)
    }
    if not targets:
        return content
    try:
        value = json.loads(content)
    except (ValueError, TypeError):
        return content
    count = 0

    def visit(node):
        nonlocal count
        if isinstance(node, list):
            for item in node:
                visit(item)
        elif isinstance(node, dict):
            for key, child in node.items():
                if key == "evidence" and isinstance(child, list):
                    for citation in child:
                        if not isinstance(citation, dict):
                            continue
                        reference = citation.get("reference")
                        if not isinstance(reference, str) or reference not in targets:
                            continue
                        if not isinstance(citation.get("kind"), str) or citation[
                            "kind"
                        ] not in {"source_fact", "visual_observation", "ai_inference"}:
                            continue
                        if not isinstance(citation.get("source_type"), str) or citation[
                            "source_type"
                        ] not in {
                            "steam_field",
                            "video_id",
                            "channel_field",
                            "visual_asset",
                            "public_link",
                            "intermediate_output",
                        }:
                            continue
                        if (
                            citation["source_type"] != "intermediate_output"
                            or citation["kind"] != "ai_inference"
                        ):
                            citation["source_type"] = "intermediate_output"
                            citation["kind"] = "ai_inference"
                            count += 1
                visit(child)

    visit(value)
    if not count:
        return content
    emit(
        "analysis_evidence_identity_normalized",
        count=count,
        reason="exact_intermediate_catalog_identity",
        call_id=last_model_call_id(),
    )
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
