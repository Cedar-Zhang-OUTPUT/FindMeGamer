"""Stable creator keys shared by profiles and analysis jobs."""


def creator_job_identity(platform: str, account_id: str) -> str:
    if (
        platform not in {"youtube", "x", "twitch", "instagram"}
        or not account_id
        or account_id.strip() != account_id
    ):
        raise ValueError("Invalid creator identity")
    return account_id if platform == "youtube" else f"{platform}:{account_id}"
