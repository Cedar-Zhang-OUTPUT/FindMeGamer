"""Strict AI-stage contracts for game analysis.

Steam identity, public metrics, media URLs, and other public facts remain owned by
``app.analysis.contracts.SteamGameSource`` and the profile repository.  These
models contain only extraction, analysis, and brief content.  Tasks 9 and 10
combine the two boundaries atomically; AI output must never regenerate source
identity or private publisher metrics.
"""

from collections.abc import Iterator
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

Confidence = Literal["low", "medium", "high"]
EvidenceKind = Literal["source_fact", "visual_observation", "ai_inference"]
EvidenceSourceType = Literal[
    "steam_field",
    "video_id",
    "channel_field",
    "visual_asset",
    "public_link",
    "intermediate_output",
]
MAX_GAME_BRIEF_JSON_BYTES = 16_000
MAX_CREATOR_BRIEF_JSON_BYTES = 4_500
MAX_SCREENING_PROMPT_OVERHEAD_BYTES = 100_000


def _bounded_text(value: str) -> str:
    if value != value.strip() or not value.strip():
        raise ValueError("text must be nonblank without surrounding whitespace")
    if any(ord(character) < 32 and character not in "\n\t" for character in value):
        raise ValueError("text contains unsupported control characters")
    return value


def _unique_texts(values: tuple[str, ...]) -> tuple[str, ...]:
    normalized = [value.casefold() for value in values]
    if len(normalized) != len(set(normalized)):
        raise ValueError("values must be unique")
    return values


def _evidence_reference(value: str) -> str:
    if any(character.isspace() or ord(character) < 32 for character in value):
        raise ValueError("evidence references cannot contain whitespace or controls")
    return value


ShortText = Annotated[
    str,
    Field(min_length=1, max_length=512),
    AfterValidator(_bounded_text),
]
LongText = Annotated[
    str,
    Field(min_length=1, max_length=4_000),
    AfterValidator(_bounded_text),
]
ReferenceText = Annotated[
    str,
    Field(min_length=1, max_length=512),
    AfterValidator(_evidence_reference),
]
TextValues = Annotated[
    tuple[ShortText, ...],
    Field(min_length=1, max_length=20),
    AfterValidator(_unique_texts),
]
BriefText = Annotated[
    str,
    Field(min_length=1, max_length=240),
    AfterValidator(_bounded_text),
]
BriefItem = Annotated[
    str,
    Field(min_length=1, max_length=72),
    AfterValidator(_bounded_text),
]
BriefValues = Annotated[
    tuple[BriefItem, ...],
    Field(min_length=1, max_length=4),
    AfterValidator(_unique_texts),
]
BriefReferenceText = Annotated[
    str,
    Field(min_length=1, max_length=96),
    AfterValidator(_evidence_reference),
]


class StrictAIModel(BaseModel):
    """Closed, immutable base used by every nested structured-output model."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        validate_default=True,
    )


class StageOutput(StrictAIModel):
    english_language_check: Literal[True]

    @field_validator("english_language_check", mode="before")
    @classmethod
    def _require_literal_boolean_true(cls, value: object) -> object:
        if type(value) is not bool or value is not True:
            raise ValueError("english_language_check must be the boolean true")
        return value


class EvidenceReference(StrictAIModel):
    kind: EvidenceKind
    source_type: EvidenceSourceType
    reference: ReferenceText
    observation: LongText

    @model_validator(mode="after")
    def _validate_reference_kind(self) -> "EvidenceReference":
        if self.kind == "visual_observation" and self.source_type != "visual_asset":
            raise ValueError("visual observations must reference a visual asset")
        if self.kind == "source_fact" and self.source_type in {
            "visual_asset",
            "intermediate_output",
        }:
            raise ValueError(
                "source facts must reference a supplied public source field"
            )
        return self


class EvidenceCatalogEntry(StrictAIModel):
    reference: ReferenceText
    source_type: EvidenceSourceType
    allowed_kinds: Annotated[
        tuple[EvidenceKind, ...],
        Field(min_length=1, max_length=3),
    ]

    @field_validator("allowed_kinds")
    @classmethod
    def _reject_duplicate_kinds(
        cls, values: tuple[EvidenceKind, ...]
    ) -> tuple[EvidenceKind, ...]:
        if len(values) != len(set(values)):
            raise ValueError("catalog evidence kinds must be unique")
        return values


class EvidenceCatalog(StrictAIModel):
    """Exact reference IDs supplied to one structured-output stage."""

    entries: Annotated[tuple[EvidenceCatalogEntry, ...], Field(max_length=1_024)]

    @field_validator("entries")
    @classmethod
    def _reject_duplicate_references(
        cls, entries: tuple[EvidenceCatalogEntry, ...]
    ) -> tuple[EvidenceCatalogEntry, ...]:
        references = [entry.reference for entry in entries]
        if len(references) != len(set(references)):
            raise ValueError("evidence catalog references must be unique")
        return entries


EvidenceReferences = Annotated[
    tuple[EvidenceReference, ...],
    Field(min_length=1, max_length=8),
]


class BriefEvidenceReference(StrictAIModel):
    kind: EvidenceKind
    source_type: EvidenceSourceType
    reference: BriefReferenceText

    @model_validator(mode="after")
    def _validate_reference_kind(self) -> "BriefEvidenceReference":
        if self.kind == "visual_observation" and self.source_type != "visual_asset":
            raise ValueError("visual observations must reference a visual asset")
        if self.kind == "source_fact" and self.source_type in {
            "visual_asset",
            "intermediate_output",
        }:
            raise ValueError(
                "source facts must reference a supplied public source field"
            )
        return self


BriefEvidenceReferences = Annotated[
    tuple[BriefEvidenceReference, ...],
    Field(min_length=1, max_length=2),
]


class UnavailableClaim(StrictAIModel):
    status: Literal["unavailable"]
    reason: LongText


class AvailableTextClaim(StrictAIModel):
    status: Literal["available"]
    value: LongText
    evidence: EvidenceReferences
    confidence: Confidence


class AvailableListClaim(StrictAIModel):
    status: Literal["available"]
    values: TextValues
    evidence: EvidenceReferences
    confidence: Confidence


EvidenceText = Annotated[
    AvailableTextClaim | UnavailableClaim,
    Field(discriminator="status"),
]
EvidenceList = Annotated[
    AvailableListClaim | UnavailableClaim,
    Field(discriminator="status"),
]


class CompactUnavailableClaim(StrictAIModel):
    status: Literal["unavailable"]
    reason: BriefText


class CompactAvailableTextClaim(StrictAIModel):
    status: Literal["available"]
    value: BriefText
    evidence: BriefEvidenceReferences
    confidence: Confidence


class CompactAvailableListClaim(StrictAIModel):
    status: Literal["available"]
    values: BriefValues
    evidence: BriefEvidenceReferences
    confidence: Confidence


CompactEvidenceText = Annotated[
    CompactAvailableTextClaim | CompactUnavailableClaim,
    Field(discriminator="status"),
]
CompactEvidenceList = Annotated[
    CompactAvailableListClaim | CompactUnavailableClaim,
    Field(discriminator="status"),
]


class GameExtraction(StageOutput):
    short_summary: EvidenceText
    core_gameplay_loop: EvidenceText
    themes: EvidenceList
    tone: EvidenceList
    target_audience: EvidenceList
    key_selling_points: EvidenceList
    content_hooks: EvidenceList
    comparable_games: EvidenceList
    suitable_creator_types: EvidenceList
    promotion_risks: EvidenceList


class GameVisualAnalysis(StageOutput):
    status: Literal["available", "unavailable"]
    unavailable_reason: LongText | None
    visual_style: EvidenceText
    visual_motifs: EvidenceList
    readability: EvidenceText
    content_hook_observations: EvidenceList

    @model_validator(mode="after")
    def _validate_visual_availability(self) -> "GameVisualAnalysis":
        claims = (
            self.visual_style,
            self.visual_motifs,
            self.readability,
            self.content_hook_observations,
        )
        if self.status == "unavailable":
            if self.unavailable_reason is None or any(
                claim.status != "unavailable" for claim in claims
            ):
                raise ValueError(
                    "unavailable visual analysis requires a reason and unavailable claims"
                )
            return self
        if self.unavailable_reason is not None:
            raise ValueError(
                "available visual analysis cannot carry an unavailable reason"
            )
        if not any(claim.status == "available" for claim in claims):
            raise ValueError("available visual analysis requires an available claim")
        for claim in claims:
            if claim.status == "available" and any(
                item.kind != "visual_observation" for item in claim.evidence
            ):
                raise ValueError(
                    "available visual claims require visual-observation evidence"
                )
        return self


class GameBrief(StrictAIModel):
    """Detailed matching input generated from validated analysis stages."""

    positioning_premise: CompactEvidenceText
    core_gameplay_loop: CompactEvidenceText
    genres: CompactEvidenceList
    themes: CompactEvidenceList
    tone: CompactEvidenceList
    visual_identity: CompactEvidenceText
    target_audience: CompactEvidenceList
    key_selling_points: CompactEvidenceList
    content_hooks: CompactEvidenceList
    comparable_games: CompactEvidenceList
    suitable_creator_types: CompactEvidenceList
    promotion_risks: CompactEvidenceList

    @model_validator(mode="after")
    def _enforce_serialized_budget(self) -> "GameBrief":
        if len(self.model_dump_json().encode("utf-8")) > MAX_GAME_BRIEF_JSON_BYTES:
            raise ValueError("GameBrief exceeds its screening serialization budget")
        return self


class GameSynthesis(StageOutput):
    """All final AI-owned Game Profile fields plus the matching brief."""

    short_summary: EvidenceText
    core_gameplay_loop: EvidenceText
    themes: EvidenceList
    visual_style: EvidenceText
    tone: EvidenceList
    target_audience: EvidenceList
    key_selling_points: EvidenceList
    content_hooks: EvidenceList
    comparable_games: EvidenceList
    suitable_creator_types: EvidenceList
    promotion_risks: EvidenceList
    game_brief: GameBrief


def validate_stage_evidence(output: StageOutput, catalog: EvidenceCatalog) -> None:
    """Reject references not present in the exact stage input catalog.

    Tasks 9 and 10 must call this immediately after structured parsing and before
    persistence.  The catalog must be the same instance serialized into the prompt;
    Vision callers must additionally derive it from the exact URL list sent to the
    provider.
    """

    if not isinstance(output, StageOutput) or not isinstance(catalog, EvidenceCatalog):
        raise TypeError("evidence binding requires a stage output and EvidenceCatalog")
    allowed = {entry.reference: entry for entry in catalog.entries}
    for reference in _iter_evidence_references(output):
        entry = allowed.get(reference.reference)
        if (
            entry is None
            or entry.source_type != reference.source_type
            or reference.kind not in entry.allowed_kinds
        ):
            raise ValueError("evidence reference is not bound to the supplied catalog")


def _iter_evidence_references(
    value: object,
) -> Iterator[EvidenceReference | BriefEvidenceReference]:
    if isinstance(value, EvidenceReference | BriefEvidenceReference):
        yield value
        return
    if isinstance(value, BaseModel):
        for field_name in type(value).model_fields:
            yield from _iter_evidence_references(getattr(value, field_name))
        return
    if isinstance(value, tuple):
        for item in value:
            yield from _iter_evidence_references(item)


def require_visual_evidence(
    claims: tuple[AvailableTextClaim | AvailableListClaim | UnavailableClaim, ...],
) -> None:
    """Validate that available thumbnail/image claims are visual observations."""

    for claim in claims:
        if claim.status == "available" and any(
            item.kind != "visual_observation" for item in claim.evidence
        ):
            raise ValueError(
                "available visual claims require visual-observation evidence"
            )
