"""Versioned, credential-free curated material; no network acquisition."""

from datetime import UTC, datetime
from typing import Annotated, Literal
from urllib.parse import urlsplit, parse_qsl
import re

from pydantic import AwareDatetime, Field, AfterValidator, model_validator

from app.schemas.ai_creator import CreatorSynthesis, URLValue, EmailValue
from app.schemas.ai_game import StrictAIModel, LongText


def public_url(value: str) -> str:
    parts = urlsplit(value)
    if (
        parts.username
        or parts.password
        or any(
            re.search(
                r"token|secret|password|api.?key|signature|credential|authorization",
                key,
                re.I,
            )
            for key, _ in parse_qsl(parts.query)
        )
    ):
        raise ValueError("credential-bearing URL is forbidden")
    return value


PublicURL = Annotated[URLValue, AfterValidator(public_url)]
Text = Annotated[str, Field(min_length=1, max_length=4000)]
Precision = Literal["exact", "rounded", "unknown"]


class Metric(StrictAIModel):
    name: Literal[
        "views",
        "likes",
        "comments",
        "vod_views",
        "clip_views",
        "live_viewers",
        "duration_seconds",
        "media_count",
        "following_count",
        "average_concurrent_viewers",
        "paid_subscribers",
    ]
    value: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    observed_at: AwareDatetime
    precision: Precision
    source_url: PublicURL | None = None
    period_start: AwareDatetime | None = None
    period_end: AwareDatetime | None = None


class ContentLanguage(StrictAIModel):
    code: Annotated[str, Field(min_length=2, max_length=35)]
    basis: Literal["platform_metadata", "observed_content", "creator_statement"]
    source_url: PublicURL


class Work(StrictAIModel):
    work_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")]
    platform_content_id: Text | None = None
    url: PublicURL
    kind: Literal["post", "reel", "carousel", "vod", "clip", "stream"]
    title_original: Text | None = None
    caption_original: Text | None = None
    published_at: AwareDatetime | None = None
    language: Text | None = None
    game_names: list[Text] = Field(default_factory=list)
    thumbnail_url: PublicURL | None = None
    metrics: list[Metric] = Field(default_factory=list)
    summary_en: Text | None = None


class Contact(StrictAIModel):
    email: EmailValue
    purpose: Annotated[str, Field(min_length=1, max_length=512)]
    source_url: PublicURL
    observed_at: AwareDatetime


class Observation(StrictAIModel):
    work_id: str | None = None
    basis: Literal[
        "metadata_only", "viewed_excerpt", "viewed_full", "profile_statement"
    ]
    observation_en: LongText
    source_url: PublicURL
    time_range: Text | None = None
    observed_at: AwareDatetime


class CuratedAnalysis(StrictAIModel):
    analyzed_at: AwareDatetime
    synthesis: CreatorSynthesis


class CreatorImportRecord(StrictAIModel):
    platform: Literal["twitch", "instagram"]
    platform_account_id: (
        Annotated[str, Field(pattern=r"^(?:[0-9]{1,128}|ig-[a-z0-9_.]{1,30})$")] | None
    ) = None
    account_id_source_url: PublicURL | None = None
    profile_url: PublicURL
    username: Annotated[str, Field(pattern=r"^[A-Za-z0-9_.]{1,30}$")]
    display_name: Annotated[str, Field(min_length=1, max_length=255)]
    collected_at: AwareDatetime
    bio_original: Text | None = None
    avatar_url: PublicURL | None = None
    website_url: PublicURL | None = None
    followers_count: Annotated[int, Field(ge=0, strict=True)] | None = None
    followers_precision: Precision
    content_languages: list[ContentLanguage] = Field(default_factory=list)
    public_location: Text | None = None
    platform_metrics: list[Metric] = Field(default_factory=list)
    works: list[Work] = Field(default_factory=list)
    contacts: list[Contact] = Field(default_factory=list)
    observations: list[Observation] = Field(default_factory=list)
    collection_notes: Text | None = None
    analysis: CuratedAnalysis | None = None

    @model_validator(mode="after")
    def validate_sources(self):
        profile = urlsplit(self.profile_url)
        hosts = {
            "twitch": {"www.twitch.tv", "twitch.tv"},
            "instagram": {"www.instagram.com", "instagram.com"},
        }[self.platform]
        if (
            profile.hostname not in hosts
            or profile.query
            or profile.fragment
            or profile.path.strip("/").lower() != self.username.lower()
            or self.username.lower()
            in {"p", "reel", "explore", "videos", "directory", "search"}
        ):
            raise ValueError(
                "profile URL and platform username must identify the same account"
            )
        provisional = bool(
            self.platform_account_id and self.platform_account_id.startswith("ig-")
        )
        if provisional and (
            self.platform != "instagram"
            or self.platform_account_id != f"ig-{self.username.lower()}"
            or self.account_id_source_url is not None
        ):
            raise ValueError(
                "provisional Instagram identity requires its lowercase username and no claimed platform ID source"
            )
        if (
            self.platform_account_id
            and not provisional
            and not self.account_id_source_url
        ):
            raise ValueError("resolved identity requires account_id_source_url")
        if self.followers_count is None and self.followers_precision != "unknown":
            raise ValueError("unknown followers require unknown precision")
        if len({c.email.casefold() for c in self.contacts}) != len(self.contacts):
            raise ValueError("duplicate contact email")
        works = {work.work_id: work for work in self.works}
        if len(works) != len(self.works):
            raise ValueError("duplicate work_id")
        kinds = {
            "twitch": {"vod", "clip", "stream"},
            "instagram": {"post", "reel", "carousel"},
        }[self.platform]
        work_hosts = hosts | (
            {"clips.twitch.tv"} if self.platform == "twitch" else set()
        )
        allowed_metrics = (
            {
                "vod_views",
                "clip_views",
                "live_viewers",
                "duration_seconds",
                "average_concurrent_viewers",
                "paid_subscribers",
            }
            if self.platform == "twitch"
            else {"views", "likes", "comments", "media_count", "following_count"}
        )
        for work in self.works:
            if work.kind not in kinds or urlsplit(work.url).hostname not in work_hosts:
                raise ValueError("work source does not match platform")
        for metric in [
            *self.platform_metrics,
            *(m for w in self.works for m in w.metrics),
        ]:
            if metric.name not in allowed_metrics:
                raise ValueError("metric does not belong to platform")
            if metric.name in {"average_concurrent_viewers", "paid_subscribers"} and (
                not metric.source_url
                or not metric.period_start
                or not metric.period_end
                or metric.period_end < metric.period_start
            ):
                raise ValueError(
                    "aggregate Twitch metrics require source and reporting period"
                )
        for observation in self.observations:
            if observation.work_id is None:
                if (
                    observation.basis != "profile_statement"
                    or observation.source_url.rstrip("/")
                    != self.profile_url.rstrip("/")
                ):
                    raise ValueError(
                        "profile observation requires matching profile source"
                    )
            elif (
                observation.work_id not in works
                or observation.source_url != works[observation.work_id].url
            ):
                raise ValueError("observation must reference its supplied work URL")
            if observation.basis == "viewed_excerpt" and not observation.time_range:
                raise ValueError("viewed excerpt requires a time range")
        if self.analysis:
            if (
                self.analysis.analyzed_at < self.collected_at
                or self.analysis.analyzed_at > datetime.now(UTC)
            ):
                raise ValueError(
                    "analysis timestamp must follow collection and not be in the future"
                )
            self._validate_analysis_binding()
        return self

    def _validate_analysis_binding(self):
        # Common schemas retain legacy source-type vocabulary. Curated references
        # use public_link, never pretend to be a YouTube video or visual asset.
        references = {"profile": self.profile_url}
        references.update({f"work:{w.work_id}": w.url for w in self.works})
        references.update(
            {f"observation:{i}": o.source_url for i, o in enumerate(self.observations)}
        )

        def visit(value):
            if isinstance(value, dict):
                if "reference" in value and "kind" in value:
                    if (
                        value["reference"] not in references
                        or value.get("source_type") != "public_link"
                        or value["kind"] == "visual_observation"
                    ):
                        raise ValueError(
                            "analysis evidence is not bound to curated public sources"
                        )
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)

        synthesis = self.analysis.synthesis
        visit(synthesis.model_dump(mode="json"))
        if any(
            selection.status != "unavailable"
            for selection in (
                synthesis.public_email,
                synthesis.linked_site,
                synthesis.social_links,
            )
        ):
            raise ValueError("curated contacts belong in contacts, not AI selections")


class CreatorImport(StrictAIModel):
    schema_version: Literal[1]
    records: list[CreatorImportRecord] = Field(min_length=1, max_length=1000)

    @model_validator(mode="before")
    @classmethod
    def normalize_collection(cls, value):
        if isinstance(value, dict) and "collection_schema_version" in value:
            if set(value) != {"collection_schema_version", "creators"}:
                raise ValueError("unsupported collection envelope fields")
            return {
                "schema_version": value["collection_schema_version"],
                "records": value["creators"],
            }
        return value
