import re
import unicodedata
from dataclasses import dataclass, replace
from typing import Protocol
from urllib.parse import urlsplit

from app.db.models.enums import TargetType


_steam_path = re.compile(r"^/app/(?P<app_id>[0-9]+)(?:/[A-Za-z0-9_-]+)?/?$")
_youtube_channel_path = re.compile(
    r"^/channel/(?P<channel_id>UC[A-Za-z0-9_-]{6,126})/?$"
)
_youtube_handle_path = re.compile(r"^/(?P<handle>@[A-Za-z0-9._-]{3,30})/?$")


class InvalidTarget(ValueError):
    """The supplied target URL is unsupported or malformed."""


class ChannelResolutionUnavailable(RuntimeError):
    """A Handle cannot be resolved safely in the current process."""


@dataclass(frozen=True)
class CanonicalTarget:
    target_type: TargetType
    canonical_id: str
    canonical_url: str
    requires_resolution: bool = False


class ChannelResolver(Protocol):
    def resolve_channel(self, target: CanonicalTarget) -> str: ...


class UnavailableChannelResolver:
    def resolve_channel(self, target: CanonicalTarget) -> str:
        raise ChannelResolutionUnavailable(
            "YouTube Handle resolution is not configured."
        )


def _parsed_https_url(raw_url: str):
    if not isinstance(raw_url, str) or not raw_url or len(raw_url) > 2048:
        raise InvalidTarget("The target URL is invalid.")
    if any(
        character.isspace() or unicodedata.category(character).startswith("C")
        for character in raw_url
    ):
        raise InvalidTarget("The target URL is invalid.")
    try:
        parsed = urlsplit(raw_url)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        raise InvalidTarget("The target URL is invalid.") from None
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or not hostname
        or parsed.netloc.casefold() != hostname.casefold()
    ):
        raise InvalidTarget("The target URL is invalid.")
    return parsed


def canonicalize_target(target_type: TargetType, raw_url: str) -> CanonicalTarget:
    parsed = _parsed_https_url(raw_url)
    hostname = parsed.hostname.casefold()
    if "%" in parsed.path or "\\" in parsed.path:
        raise InvalidTarget("The target URL is invalid.")

    if target_type is TargetType.GAME:
        if hostname != "store.steampowered.com":
            raise InvalidTarget("The target URL is invalid.")
        match = _steam_path.fullmatch(parsed.path)
        if match is None:
            raise InvalidTarget("The target URL is invalid.")
        numeric_app_id = int(match.group("app_id"))
        if not 1 <= numeric_app_id <= 2_147_483_647:
            raise InvalidTarget("The target URL is invalid.")
        app_id = str(numeric_app_id)
        return CanonicalTarget(
            target_type=target_type,
            canonical_id=app_id,
            canonical_url=f"https://store.steampowered.com/app/{app_id}",
        )

    if target_type is TargetType.CREATOR:
        if hostname in {"x.com", "www.x.com", "twitter.com", "www.twitter.com"}:
            account = re.fullmatch(r"/i/user/([1-9][0-9]{0,19})/?", parsed.path)
            if account:
                account_id = account.group(1)
                return CanonicalTarget(
                    target_type, f"x:{account_id}", f"https://x.com/i/user/{account_id}"
                )
            username = re.fullmatch(r"/([A-Za-z0-9_]{1,15})/?", parsed.path)
            if username and username.group(1).casefold() not in {
                "home",
                "explore",
                "search",
                "settings",
                "messages",
                "notifications",
                "i",
                "intent",
                "compose",
            }:
                handle = username.group(1).casefold()
                return CanonicalTarget(
                    target_type, f"x:@{handle}", f"https://x.com/{handle}", True
                )
            raise InvalidTarget("The target URL is invalid.")
        if hostname not in {"youtube.com", "www.youtube.com"}:
            raise InvalidTarget("The target URL is invalid.")
        channel_match = _youtube_channel_path.fullmatch(parsed.path)
        if channel_match is not None:
            channel_id = channel_match.group("channel_id")
            return CanonicalTarget(
                target_type=target_type,
                canonical_id=channel_id,
                canonical_url=f"https://www.youtube.com/channel/{channel_id}",
            )
        handle_match = _youtube_handle_path.fullmatch(parsed.path)
        if handle_match is not None:
            handle = handle_match.group("handle").casefold()
            return CanonicalTarget(
                target_type=target_type,
                canonical_id=handle,
                canonical_url=f"https://www.youtube.com/{handle}",
                requires_resolution=True,
            )
    raise InvalidTarget("The target URL is invalid.")


def resolve_target(
    target_type: TargetType,
    raw_url: str,
    resolver: ChannelResolver,
) -> CanonicalTarget:
    target = canonicalize_target(target_type, raw_url)
    if not target.requires_resolution:
        return target
    channel_id = resolver.resolve_channel(target)
    if target.canonical_id.startswith("x:@"):
        if (
            not isinstance(channel_id, str)
            or re.fullmatch(r"[1-9][0-9]{0,19}", channel_id) is None
        ):
            raise InvalidTarget("The resolved X account ID is invalid.")
        return replace(
            target,
            canonical_id=f"x:{channel_id}",
            canonical_url=f"https://x.com/i/user/{channel_id}",
            requires_resolution=False,
        )
    if _youtube_channel_path.fullmatch(f"/channel/{channel_id}") is None:
        raise InvalidTarget("The resolved YouTube Channel ID is invalid.")
    return replace(
        target,
        canonical_id=channel_id,
        canonical_url=f"https://www.youtube.com/channel/{channel_id}",
        requires_resolution=False,
    )
