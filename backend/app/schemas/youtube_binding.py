from pydantic import Field, StrictInt, field_validator
from app.schemas.outreach_drafts import StrictInput
from app.analysis.targets import canonicalize_target, creator_platform
from app.db.models.enums import TargetType


class YouTubeBinding(StrictInput):
    url: str = Field(min_length=1, max_length=2048)
    expected_revision: StrictInt = Field(ge=0)

    @field_validator("url")
    @classmethod
    def canonical_youtube(cls, value):
        target = canonicalize_target(TargetType.CREATOR, value)
        if creator_platform(target.canonical_id) != "youtube":
            raise ValueError("A YouTube channel URL is required.")
        return target.canonical_url
