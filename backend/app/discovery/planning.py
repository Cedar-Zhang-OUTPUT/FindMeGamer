import re
from pydantic import BaseModel, Field, model_validator

from app.analysis.targets import canonicalize_target
from app.analysis.creator_identity import creator_job_identity
from app.db.models.enums import TargetType


class HomepageCandidate(BaseModel):
    platform: str
    platform_account_id: str
    display_name: str = Field(min_length=1, max_length=512)
    canonical_url: str
    followers: int | None = Field(default=None, ge=0)
    content_languages: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def identity(self):
        target = canonicalize_target(TargetType.CREATOR, self.canonical_url)
        if target.requires_resolution or target.canonical_id != creator_job_identity(
            self.platform, self.platform_account_id
        ):
            raise ValueError("Candidate identity mismatch")
        self.canonical_url = target.canonical_url
        self.content_languages = sorted(
            {
                normalize_language(v)
                for v in self.content_languages
                if normalize_language(v)
            }
        )
        return self


def normalize_language(value):
    if not isinstance(value, str):
        return None
    value = value.lower().replace("_", "-").split("-")[0]
    return (
        value
        if re.fullmatch("[a-z]{2,3}", value) and value not in {"und", "zxx"}
        else None
    )


def matches(candidate, conditions):
    if conditions.content_languages and not set(
        candidate.content_languages
    ).intersection(conditions.content_languages):
        return False
    if conditions.min_followers is not None and (
        candidate.followers is None or candidate.followers < conditions.min_followers
    ):
        return False
    if conditions.max_followers is not None and (
        candidate.followers is None or candidate.followers > conditions.max_followers
    ):
        return False
    return True


def _claim_values(section, key):
    claim = section.get(key, {})
    if not isinstance(claim, dict):
        return []
    values = claim.get("values", [])
    return (
        [v for v in values if isinstance(v, str) and v.strip()]
        if isinstance(values, list)
        else []
    )


def build_plan(snapshot, keywords):
    """Small alternative queries; comparable games are never a required intersection."""

    def clean(value):
        return " ".join(re.findall(r"[\w]+", value, flags=re.UNICODE))[:140]

    name = clean(snapshot["name"])
    keywords = clean(keywords)
    brief = snapshot.get("brief", {})
    analysis = snapshot.get("analysis", {})
    genres = _claim_values(brief, "genres")
    hooks = _claim_values(brief, "content_hooks") or _claim_values(
        analysis, "content_hooks"
    )
    comparable = _claim_values(brief, "comparable_games") or _claim_values(
        analysis, "comparable_games"
    )
    queries = [f"{name} {keywords} gameplay".strip()]
    if genres:
        queries.append(f"{clean(genres[0])} {keywords} gameplay".strip())
    if comparable:
        queries.append(f"{clean(comparable[0])} {keywords} gameplay".strip())
    elif hooks:
        queries.append(f"{name} {clean(hooks[0])} {keywords}".strip())
    return list(dict.fromkeys(queries))[:3]
