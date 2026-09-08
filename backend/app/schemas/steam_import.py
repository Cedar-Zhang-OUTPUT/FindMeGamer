from uuid import UUID
from pydantic import Field, StrictInt, field_validator, model_validator
from app.schemas.outreach_drafts import StrictInput
from app.analysis.targets import canonicalize_target
from app.db.models.enums import TargetType


class SteamImport(StrictInput):
    url: str = Field(min_length=1, max_length=2048)
    game_id: UUID | None = None
    expected_revision: StrictInt | None = Field(default=None, ge=0)

    @field_validator("url")
    @classmethod
    def canonical_steam_url(cls, value):
        return canonicalize_target(TargetType.GAME, value).canonical_url

    @model_validator(mode="after")
    def explicit_binding(self):
        if (self.game_id is None) != (self.expected_revision is None):
            raise ValueError("Selected Game binding requires its current revision.")
        return self
