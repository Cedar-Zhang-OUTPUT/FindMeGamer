import pytest

from app.analysis.targets import (
    CanonicalTarget,
    InvalidTarget,
    canonicalize_target,
    resolve_target,
)
from app.db.models.enums import TargetType


@pytest.mark.parametrize(
    ("target_type", "url", "expected"),
    [
        (
            TargetType.GAME,
            "https://store.steampowered.com/app/1245620/ELDEN_RING/",
            "1245620",
        ),
        (
            TargetType.CREATOR,
            "https://www.youtube.com/channel/UCabc123",
            "UCabc123",
        ),
        (
            TargetType.CREATOR,
            "https://www.youtube.com/@ExampleCreator",
            "@examplecreator",
        ),
    ],
)
def test_canonical_target(
    target_type: TargetType, url: str, expected: str
) -> None:
    assert canonicalize_target(target_type, url).canonical_id == expected


@pytest.mark.parametrize(
    ("url", "expected_id", "expected_url"),
    [
        (
            "https://store.steampowered.com/app/001245620/ELDEN_RING"
            "?l=english#reviews",
            "1245620",
            "https://store.steampowered.com/app/1245620",
        ),
        (
            "https://store.steampowered.com/app/1/",
            "1",
            "https://store.steampowered.com/app/1",
        ),
    ],
)
def test_steam_variants_have_one_canonical_identity(
    url: str, expected_id: str, expected_url: str
) -> None:
    target = canonicalize_target(TargetType.GAME, url)
    assert target.canonical_id == expected_id
    assert target.canonical_url == expected_url


@pytest.mark.parametrize(
    "url",
    [
        "http://store.steampowered.com/app/1245620",
        "https://store.steampowered.com:443/app/1245620",
        "https://store.steampowered.com:/app/1245620",
        "https://user@store.steampowered.com/app/1245620",
        "https://store.steampowered.com.evil.example/app/1245620",
        "https://evil.store.steampowered.com/app/1245620",
        "https://store.steampowered.com/app/",
        "https://store.steampowered.com/app/0",
        "https://store.steampowered.com/app/-1",
        "https://store.steampowered.com/app/12%2F34",
        "https://store.steampowered.com/app/1245620/slug/extra",
        "https://store.steampowered.com/app/2147483648",
        "https://www.youtube.com/channel/UCabc123",
    ],
)
def test_steam_rejects_non_store_app_shapes(url: str) -> None:
    with pytest.raises(InvalidTarget):
        canonicalize_target(TargetType.GAME, url)


@pytest.mark.parametrize(
    ("url", "expected_id", "expected_url", "requires_resolution"),
    [
        (
            "https://youtube.com/channel/UCabc123/?view_as=subscriber#about",
            "UCabc123",
            "https://www.youtube.com/channel/UCabc123",
            False,
        ),
        (
            "https://www.youtube.com/@Example.Creator?sub_confirmation=1",
            "@example.creator",
            "https://www.youtube.com/@example.creator",
            True,
        ),
    ],
)
def test_youtube_variants_have_one_canonical_identity(
    url: str,
    expected_id: str,
    expected_url: str,
    requires_resolution: bool,
) -> None:
    target = canonicalize_target(TargetType.CREATOR, url)
    assert target.canonical_id == expected_id
    assert target.canonical_url == expected_url
    assert target.requires_resolution is requires_resolution


@pytest.mark.parametrize(
    "url",
    [
        "http://youtube.com/channel/UCabc123",
        "https://youtube.com:443/channel/UCabc123",
        "https://youtube.com:/channel/UCabc123",
        "https://user:pass@youtube.com/channel/UCabc123",
        "https://youtube.com.evil.example/channel/UCabc123",
        "https://evil.youtube.com/channel/UCabc123",
        "https://youtube.com/channel/",
        "https://youtube.com/channel/UCabc",
        "https://youtube.com/channel/UCabc123/extra",
        "https://youtube.com/channel/UCabc%2F123",
        "https://youtube.com/@ab",
        "https://youtube.com/@example%2Fcreator",
        "https://youtube.com/c/example",
        "https://youtube.com/user/example",
        "https://store.steampowered.com/app/1245620",
    ],
)
def test_youtube_rejects_non_channel_and_malformed_shapes(url: str) -> None:
    with pytest.raises(InvalidTarget):
        canonicalize_target(TargetType.CREATOR, url)


class FakeChannelResolver:
    def __init__(self, channel_id: str) -> None:
        self.channel_id = channel_id
        self.targets: list[CanonicalTarget] = []

    def resolve_channel(self, target: CanonicalTarget) -> str:
        self.targets.append(target)
        return self.channel_id


def test_handle_is_resolved_to_channel_id_and_url() -> None:
    resolver = FakeChannelResolver("UCresolved123")

    target = resolve_target(
        TargetType.CREATOR,
        "https://youtube.com/@ExampleCreator",
        resolver,
    )

    assert [value.canonical_id for value in resolver.targets] == [
        "@examplecreator"
    ]
    assert target == CanonicalTarget(
        target_type=TargetType.CREATOR,
        canonical_id="UCresolved123",
        canonical_url="https://www.youtube.com/channel/UCresolved123",
    )


def test_handle_resolver_must_return_a_valid_channel_id() -> None:
    with pytest.raises(InvalidTarget):
        resolve_target(
            TargetType.CREATOR,
            "https://youtube.com/@ExampleCreator",
            FakeChannelResolver("@not-a-channel-id"),
        )
