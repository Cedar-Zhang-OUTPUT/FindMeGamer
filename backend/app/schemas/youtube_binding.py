from pydantic import Field, StrictInt, field_validator
from app.schemas.outreach_drafts import StrictInput
from app.analysis.targets import canonicalize_target
from app.db.models.enums import TargetType


class YouTubeBinding(StrictInput):
    url: str = Field(min_length=1, max_length=2048)
    expected_revision: StrictInt = Field(ge=0)

    @field_validator("url")
    @classmethod
    def canonical_youtube(cls, value):
        return canonicalize_target(TargetType.CREATOR, value).canonical_url
