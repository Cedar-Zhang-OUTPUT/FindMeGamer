from contextlib import contextmanager

from app.analysis.runtime import build_secret_provider
from app.api.routes.jobs import CeleryJobDispatcher
from app.core.config import get_settings
from app.core.database import session_scope
from app.discovery.service import DiscoverService
from app.integrations.youtube_discovery import YouTubeDiscovery
from app.integrations.x_discovery import XDiscovery


def build_discover_service():
    settings = get_settings()
    secrets = build_secret_provider(settings=settings)

    @contextmanager
    def provider_factory(platform):
        values = secrets.load((platform,))
        try:
            gateway = YouTubeDiscovery if platform == "youtube" else XDiscovery
            with gateway(
                api_key=values[platform],
                base_url=(
                    settings.youtube_api_base_url
                    if platform == "youtube"
                    else settings.x_api_base_url
                ),
            ) as provider:
                yield provider
        finally:
            values.clear()

    return DiscoverService(
        session_factory=session_scope,
        provider_factory=provider_factory,
        analysis_dispatcher=CeleryJobDispatcher(),
    )
