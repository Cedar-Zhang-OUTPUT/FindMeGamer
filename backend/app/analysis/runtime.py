"""Production dependency construction for Analysis pipelines and Handle resolution."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from contextlib import AbstractContextManager, ExitStack, contextmanager
import sys
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.creator_checkpoints import CreatorAnalysisCheckpointStore
from app.analysis.creator_map_reduce_pipeline import CreatorMapReducePipeline
from app.analysis.game_pipeline import GameAnalysisPipeline
from app.analysis.service import CreatorAnalysisService, GameAnalysisService
from app.analysis.targets import (
    CanonicalTarget,
    ChannelResolutionUnavailable,
)
from app.core.config import Settings, get_settings
from app.core.crypto import EncryptedValue, SecretCipher
from app.core.database import session_scope
from app.db.models.enums import TargetType
from app.db.models.settings import ServiceSecret
from app.integrations.deepseek import DeepSeekGateway
from app.integrations.errors import (
    PermanentIntegrationError,
    TransientIntegrationError,
)
from app.integrations.filesystem import FilesystemArtifactStore
from app.integrations.gemini_email import GeminiEmailResearchGateway
from app.integrations.public_pages import PublicPageGateway
from app.integrations.s3 import S3ArtifactStore
from app.integrations.steam import SteamGateway
from app.integrations.youtube import YouTubeGateway


SessionFactory = Callable[[], AbstractContextManager[Session]]
CipherFactory = Callable[[], SecretCipher]


def _artifact_store_for(
    settings: Settings,
) -> S3ArtifactStore | FilesystemArtifactStore:
    if settings.artifact_store == "filesystem":
        return FilesystemArtifactStore(directory=settings.artifact_directory)
    return S3ArtifactStore(
        bucket=settings.s3_bucket,
        region=settings.s3_region,
        endpoint_url=settings.s3_endpoint_url,
    )


@contextmanager
def _owned_resources():
    stack = ExitStack()
    try:
        yield stack
    except BaseException:
        primary = sys.exc_info()
        try:
            stack.__exit__(*primary)
        except BaseException:
            pass
        raise
    else:
        try:
            stack.close()
        except Exception:
            raise PermanentIntegrationError("analysis_cleanup_failed") from None


class SecretProvider(Protocol):
    def load(self, services: Iterable[str]) -> dict[str, str]: ...

    def load_optional(self, service: str) -> str | None: ...


class ProductionSecretProvider:
    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        cipher_factory: CipherFactory,
    ) -> None:
        self._session_factory = session_factory
        self._cipher_factory = cipher_factory

    def load(self, services: Iterable[str]) -> dict[str, str]:
        required = tuple(services)
        if (
            not required
            or len(required) != len(set(required))
            or any(
                service not in {"youtube", "deepseek", "google_ai"}
                for service in required
            )
        ):
            raise PermanentIntegrationError("analysis_configuration_invalid")
        with self._session_factory() as session:
            rows = session.scalars(
                select(ServiceSecret).where(ServiceSecret.service.in_(required))
            ).all()
            encrypted = {
                row.service: EncryptedValue(
                    ciphertext=bytes(row.ciphertext), nonce=bytes(row.nonce)
                )
                for row in rows
                if row.service in required
            }
        if set(encrypted) != set(required):
            raise PermanentIntegrationError("analysis_configuration_invalid")
        try:
            cipher = self._cipher_factory()
            return {service: cipher.decrypt(encrypted[service]) for service in required}
        except Exception:
            raise PermanentIntegrationError("analysis_configuration_invalid") from None

    def load_optional(self, service: str) -> str | None:
        if service not in {"youtube", "deepseek", "google_ai"}:
            raise PermanentIntegrationError("analysis_configuration_invalid")
        with self._session_factory() as session:
            row = session.scalar(
                select(ServiceSecret).where(ServiceSecret.service == service)
            )
            encrypted = (
                EncryptedValue(ciphertext=bytes(row.ciphertext), nonce=bytes(row.nonce))
                if row is not None
                else None
            )
        if encrypted is None:
            return None
        try:
            return self._cipher_factory().decrypt(encrypted)
        except Exception:
            raise PermanentIntegrationError("analysis_configuration_invalid") from None


class ProductionAnalysisRuntime:
    def __init__(
        self,
        *,
        settings: Settings,
        session_factory: SessionFactory,
        secret_provider: SecretProvider,
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory
        self._secret_provider = secret_provider

    @contextmanager
    def pipeline_for(self, target_type: TargetType):
        secrets_by_service: dict[str, str] = {}
        try:
            with _owned_resources() as stack:
                if target_type is TargetType.GAME:
                    secrets_by_service = self._secret_provider.load(("deepseek",))
                    steam = stack.enter_context(
                        SteamGateway(base_url=self._settings.steam_store_base_url)
                    )
                    artifacts = stack.enter_context(_artifact_store_for(self._settings))
                    deepseek = stack.enter_context(
                        DeepSeekGateway(
                            api_key=secrets_by_service["deepseek"],
                            base_url=self._settings.deepseek_api_base_url,
                        )
                    )
                    yield GameAnalysisPipeline(
                        service=GameAnalysisService(
                            session_factory=self._session_factory
                        ),
                        steam=steam,
                        artifacts=artifacts,
                        deepseek=deepseek,
                    )
                elif target_type is TargetType.CREATOR:
                    secrets_by_service = self._secret_provider.load(
                        ("youtube", "deepseek")
                    )
                    google_ai_key = self._secret_provider.load_optional("google_ai")
                    if google_ai_key is not None:
                        secrets_by_service["google_ai"] = google_ai_key
                    youtube = stack.enter_context(
                        YouTubeGateway(
                            api_key=secrets_by_service["youtube"],
                            base_url=self._settings.youtube_api_base_url,
                        )
                    )
                    artifacts = stack.enter_context(_artifact_store_for(self._settings))
                    deepseek = stack.enter_context(
                        DeepSeekGateway(
                            api_key=secrets_by_service["deepseek"],
                            base_url=self._settings.deepseek_api_base_url,
                        )
                    )
                    email_research = (
                        stack.enter_context(
                            GeminiEmailResearchGateway(
                                api_key=secrets_by_service["google_ai"],
                                base_url=self._settings.google_ai_api_base_url,
                            )
                        )
                        if "google_ai" in secrets_by_service
                        else None
                    )
                    yield CreatorMapReducePipeline(
                        service=CreatorAnalysisService(
                            session_factory=self._session_factory
                        ),
                        youtube=youtube,
                        artifacts=artifacts,
                        public_pages=PublicPageGateway(),
                        deepseek=deepseek,
                        email_research=email_research,
                        checkpoints=CreatorAnalysisCheckpointStore(
                            session_factory=self._session_factory
                        ),
                    )
                else:
                    raise PermanentIntegrationError("analysis_job_target_invalid")
        finally:
            secrets_by_service.clear()


class ProductionChannelResolver:
    def __init__(self, *, settings: Settings, secret_provider: SecretProvider) -> None:
        self._settings = settings
        self._secret_provider = secret_provider

    def resolve_channel(self, target: CanonicalTarget) -> str:
        secrets_by_service: dict[str, str] = {}
        try:
            secrets_by_service = self._secret_provider.load(("youtube",))
            with _owned_resources() as stack:
                youtube = stack.enter_context(
                    YouTubeGateway(
                        api_key=secrets_by_service["youtube"],
                        base_url=self._settings.youtube_api_base_url,
                    )
                )
                return youtube.resolve_channel(target)
        except TransientIntegrationError:
            raise ChannelResolutionUnavailable() from None
        finally:
            secrets_by_service.clear()


def build_secret_provider(
    *,
    settings: Settings | None = None,
    session_factory: SessionFactory = session_scope,
) -> ProductionSecretProvider:
    effective_settings = settings or get_settings()
    return ProductionSecretProvider(
        session_factory=session_factory,
        cipher_factory=lambda: SecretCipher.from_file(
            effective_settings.master_key_file
        ),
    )


def build_production_runtime(
    *,
    settings: Settings | None = None,
    session_factory: SessionFactory = session_scope,
) -> ProductionAnalysisRuntime:
    effective_settings = settings or get_settings()
    return ProductionAnalysisRuntime(
        settings=effective_settings,
        session_factory=session_factory,
        secret_provider=build_secret_provider(
            settings=effective_settings, session_factory=session_factory
        ),
    )


def build_production_channel_resolver(
    *,
    settings: Settings | None = None,
    session_factory: SessionFactory = session_scope,
) -> ProductionChannelResolver:
    effective_settings = settings or get_settings()
    return ProductionChannelResolver(
        settings=effective_settings,
        secret_provider=build_secret_provider(
            settings=effective_settings, session_factory=session_factory
        ),
    )
