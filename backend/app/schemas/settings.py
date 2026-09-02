from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field


class ReanalysisSettingsUpdate(BaseModel):
    creator_interval_days: Annotated[int, Field(ge=1, le=30)]
    game_interval_days: Annotated[int, Field(ge=1, le=90)]


class ReanalysisSettingsResponse(BaseModel):
    creator_interval_days: int
    game_interval_days: int


class ConnectionSecretUpdate(BaseModel):
    secret: Annotated[
        str,
        Field(min_length=1, max_length=16_384, json_schema_extra={"writeOnly": True}),
    ]


class ConnectionStatusResponse(BaseModel):
    configured: bool
    last_test_status: Literal["success", "failure"] | None
    last_tested_at: datetime | None
