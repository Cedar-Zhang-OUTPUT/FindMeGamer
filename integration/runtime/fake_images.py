"""In-memory image fixtures, injected only by the isolated integration Worker."""

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.integrations.deepseek import DeepSeekGateway


INLINE_IMAGE = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a1ioAAAAASUVORK5CYII="
)
_fixture_url = re.compile(
    r"https://images\.integration\.invalid/(?:steam/[0-9]+|youtube/video-[A-Za-z0-9_-]+)\.png"
)


class FakeImageLoader:
    def load(self, url: str) -> str:
        if not _fixture_url.fullmatch(url):
            from app.integrations.errors import PermanentIntegrationError

            raise PermanentIntegrationError("integration_image_fixture_unknown")
        return INLINE_IMAGE


def image_gateway(**kwargs) -> "DeepSeekGateway":
    from app.integrations.deepseek import DeepSeekGateway

    return DeepSeekGateway(**kwargs, image_loader=FakeImageLoader())
