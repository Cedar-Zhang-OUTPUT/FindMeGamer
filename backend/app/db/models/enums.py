from enum import StrEnum


class TargetType(StrEnum):
    GAME = "game"
    CREATOR = "creator"


class JobMode(StrEnum):
    CREATE = "create"
    REANALYZE = "reanalyze"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class AnalysisStage(StrEnum):
    FETCHING_DATA = "fetching_data"
    ANALYZING = "analyzing"
    FINALIZING = "finalizing"
