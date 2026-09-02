from contextlib import contextmanager

import pytest
from sqlalchemy.orm import Session

from app.analysis.runtime import (
    ProductionAnalysisRuntime,
    ProductionChannelResolver,
    ProductionSecretProvider,
)
from app.analysis.targets import CanonicalTarget
from app.analysis.targets import ChannelResolutionUnavailable
from app.core.config import get_settings
from app.core.crypto import SecretCipher
from app.db.models.enums import TargetType
from app.db.models.settings import ServiceSecret
from app.integrations.errors import PermanentIntegrationError
from app.integrations.errors import TransientIntegrationError


@contextmanager
def _session_factory(session: Session):
    yield session


def _store_secret(session: Session, service: str, plaintext: str) -> None:
    encrypted = SecretCipher(bytes(range(32))).encrypt(plaintext)
    session.add(
        ServiceSecret(
            service=service,
            ciphertext=encrypted.ciphertext,
            nonce=encrypted.nonce,
        )
    )
    session.flush()


def test_secret_provider_closes_short_session_before_key_io_and_decryption(
    session: Session,
) -> None:
    _store_secret(session, "youtube", "youtube-test-key")
    events: list[str] = []

    @contextmanager
    def tracked_factory():
        events.append("session-open")
        try:
            yield session
        finally:
            session.commit()
            events.append("session-closed")

    def cipher_factory():
        events.append("cipher-created")
        assert not session.in_transaction()
        return SecretCipher(bytes(range(32)))

    provider = ProductionSecretProvider(
        session_factory=tracked_factory,
        cipher_factory=cipher_factory,
    )
    assert provider.load(("youtube",)) == {"youtube": "youtube-test-key"}
    assert events == ["session-open", "session-closed", "cipher-created"]


@pytest.mark.parametrize("missing_service", ["youtube", "deepseek"])
def test_secret_provider_maps_missing_and_corrupt_secrets_to_safe_configuration_error(
    session: Session, missing_service: str
) -> None:
    _store_secret(session, "youtube", "youtube-test-key")
    _store_secret(session, "deepseek", "deepseek-test-key")
    if missing_service == "youtube":
        session.query(ServiceSecret).filter_by(service="youtube").delete()
    else:
        stored = session.query(ServiceSecret).filter_by(service="deepseek").one()
        stored.nonce = b"corrupt"
    session.flush()
    provider = ProductionSecretProvider(
        session_factory=lambda: _session_factory(session),
        cipher_factory=lambda: SecretCipher(bytes(range(32))),
    )
    with pytest.raises(PermanentIntegrationError) as raised:
        provider.load(("youtube", "deepseek"))
    assert raised.value.code == "analysis_configuration_invalid"
    assert "youtube-test-key" not in str(raised.value)


class ClosableGateway:
    instances: list["ClosableGateway"] = []

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.closed = False
        self.__class__.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        self.closed = True


class FakePipeline:
    def __init__(self, **dependencies) -> None:
        self.dependencies = dependencies


class CleanupFailingGateway(ClosableGateway):
    def __exit__(self, *args) -> None:
        self.closed = True
        raise RuntimeError("unsafe cleanup detail")


@pytest.mark.parametrize(
    ("target_type", "required_services", "pipeline_name", "closable_count"),
    [
        (TargetType.GAME, ("deepseek",), "GameAnalysisPipeline", 3),
        (
            TargetType.CREATOR,
            ("youtube", "deepseek"),
            "CreatorAnalysisPipeline",
            3,
        ),
    ],
)
def test_runtime_builds_existing_pipeline_and_closes_every_owned_client(
    monkeypatch: pytest.MonkeyPatch,
    target_type: TargetType,
    required_services: tuple[str, ...],
    pipeline_name: str,
    closable_count: int,
) -> None:
    ClosableGateway.instances = []
    loaded: list[tuple[str, ...]] = []

    class Secrets:
        def load(self, services):
            loaded.append(tuple(services))
            return {service: f"{service}-test-key" for service in services}

    for name in (
        "SteamGateway",
        "YouTubeGateway",
        "DeepSeekGateway",
        "S3ArtifactStore",
    ):
        monkeypatch.setattr(f"app.analysis.runtime.{name}", ClosableGateway)
    monkeypatch.setattr(f"app.analysis.runtime.{pipeline_name}", FakePipeline)
    runtime = ProductionAnalysisRuntime(
        settings=get_settings(),
        session_factory=lambda: (_ for _ in ()).throw(
            AssertionError(
                "pipeline service must not open a Session during construction"
            )
        ),
        secret_provider=Secrets(),
    )

    with runtime.pipeline_for(target_type) as pipeline:
        assert isinstance(pipeline, FakePipeline)
        assert loaded == [required_services]
        assert len(ClosableGateway.instances) == closable_count
        assert not any(instance.closed for instance in ClosableGateway.instances)

    assert all(instance.closed for instance in ClosableGateway.instances)


def test_runtime_closes_gateways_when_pipeline_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ClosableGateway.instances = []

    class Secrets:
        def load(self, services):
            return {"deepseek": "deepseek-test-key"}

    for name in ("SteamGateway", "DeepSeekGateway", "S3ArtifactStore"):
        monkeypatch.setattr(f"app.analysis.runtime.{name}", ClosableGateway)
    monkeypatch.setattr("app.analysis.runtime.GameAnalysisPipeline", FakePipeline)
    runtime = ProductionAnalysisRuntime(
        settings=get_settings(),
        session_factory=lambda: None,
        secret_provider=Secrets(),
    )
    with pytest.raises(RuntimeError):
        with runtime.pipeline_for(TargetType.GAME):
            raise RuntimeError("pipeline failed")
    assert all(instance.closed for instance in ClosableGateway.instances)


def _cleanup_failing_runtime(monkeypatch: pytest.MonkeyPatch):
    CleanupFailingGateway.instances = []

    class Secrets:
        def load(self, services):
            return {"deepseek": "deepseek-test-key"}

    for name in ("SteamGateway", "DeepSeekGateway", "S3ArtifactStore"):
        monkeypatch.setattr(f"app.analysis.runtime.{name}", CleanupFailingGateway)
    monkeypatch.setattr("app.analysis.runtime.GameAnalysisPipeline", FakePipeline)
    return ProductionAnalysisRuntime(
        settings=get_settings(),
        session_factory=lambda: None,
        secret_provider=Secrets(),
    )


def test_runtime_preserves_primary_transient_error_when_every_cleanup_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _cleanup_failing_runtime(monkeypatch)

    with pytest.raises(TransientIntegrationError) as raised:
        with runtime.pipeline_for(TargetType.GAME):
            raise TransientIntegrationError("steam_unavailable")

    assert raised.value.code == "steam_unavailable"
    assert len(CleanupFailingGateway.instances) == 3
    assert all(instance.closed for instance in CleanupFailingGateway.instances)


def test_runtime_maps_standalone_cleanup_error_to_safe_typed_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _cleanup_failing_runtime(monkeypatch)

    with pytest.raises(PermanentIntegrationError) as raised:
        with runtime.pipeline_for(TargetType.GAME):
            pass

    assert raised.value.code == "analysis_cleanup_failed"
    assert "unsafe cleanup detail" not in str(raised.value)
    assert all(instance.closed for instance in CleanupFailingGateway.instances)


def test_runtime_preserves_process_control_error_when_cleanup_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _cleanup_failing_runtime(monkeypatch)

    with pytest.raises(KeyboardInterrupt):
        with runtime.pipeline_for(TargetType.GAME):
            raise KeyboardInterrupt

    assert all(instance.closed for instance in CleanupFailingGateway.instances)


def test_production_handle_resolver_uses_short_secret_load_and_closes_youtube(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ClosableGateway.instances = []

    class Secrets:
        def load(self, services):
            assert tuple(services) == ("youtube",)
            return {"youtube": "youtube-test-key"}

    class ResolverGateway(ClosableGateway):
        def resolve_channel(self, target: CanonicalTarget) -> str:
            assert target.canonical_id == "@example"
            return "UCresolved123"

    monkeypatch.setattr("app.analysis.runtime.YouTubeGateway", ResolverGateway)
    resolver = ProductionChannelResolver(
        settings=get_settings(), secret_provider=Secrets()
    )
    target = CanonicalTarget(
        target_type=TargetType.CREATOR,
        canonical_id="@example",
        canonical_url="https://www.youtube.com/@example",
        requires_resolution=True,
    )
    assert resolver.resolve_channel(target) == "UCresolved123"
    assert len(ResolverGateway.instances) == 1
    assert ResolverGateway.instances[0].closed is True


def test_production_handle_resolver_preserves_permanent_configuration_failure() -> None:
    class Secrets:
        def load(self, services):
            raise PermanentIntegrationError("analysis_configuration_invalid")

    resolver = ProductionChannelResolver(
        settings=get_settings(), secret_provider=Secrets()
    )
    target = CanonicalTarget(
        target_type=TargetType.CREATOR,
        canonical_id="@example",
        canonical_url="https://www.youtube.com/@example",
        requires_resolution=True,
    )
    with pytest.raises(PermanentIntegrationError) as raised:
        resolver.resolve_channel(target)
    assert raised.value.code == "analysis_configuration_invalid"


def test_production_handle_resolver_preserves_permanent_target_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Secrets:
        def load(self, services):
            return {"youtube": "youtube-test-key"}

    class MissingChannelGateway(ClosableGateway):
        def resolve_channel(self, target: CanonicalTarget) -> str:
            raise PermanentIntegrationError("youtube_channel_not_found")

    monkeypatch.setattr("app.analysis.runtime.YouTubeGateway", MissingChannelGateway)
    resolver = ProductionChannelResolver(
        settings=get_settings(), secret_provider=Secrets()
    )
    target = CanonicalTarget(
        target_type=TargetType.CREATOR,
        canonical_id="@missing",
        canonical_url="https://www.youtube.com/@missing",
        requires_resolution=True,
    )
    with pytest.raises(PermanentIntegrationError) as raised:
        resolver.resolve_channel(target)
    assert raised.value.code == "youtube_channel_not_found"


def test_production_handle_resolver_maps_only_transient_integration_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Secrets:
        def load(self, services):
            return {"youtube": "youtube-test-key"}

    class UnavailableGateway(ClosableGateway):
        def resolve_channel(self, target: CanonicalTarget) -> str:
            raise TransientIntegrationError("youtube_unavailable")

    monkeypatch.setattr("app.analysis.runtime.YouTubeGateway", UnavailableGateway)
    resolver = ProductionChannelResolver(
        settings=get_settings(), secret_provider=Secrets()
    )
    target = CanonicalTarget(
        target_type=TargetType.CREATOR,
        canonical_id="@example",
        canonical_url="https://www.youtube.com/@example",
        requires_resolution=True,
    )
    with pytest.raises(ChannelResolutionUnavailable):
        resolver.resolve_channel(target)


def test_production_handle_resolver_does_not_relabel_unexpected_failure() -> None:
    class Secrets:
        def load(self, services):
            raise RuntimeError("master-key-path=/private/secret")

    resolver = ProductionChannelResolver(
        settings=get_settings(), secret_provider=Secrets()
    )
    target = CanonicalTarget(
        target_type=TargetType.CREATOR,
        canonical_id="@example",
        canonical_url="https://www.youtube.com/@example",
        requires_resolution=True,
    )
    with pytest.raises(RuntimeError) as raised:
        resolver.resolve_channel(target)
    assert "master-key-path" in str(raised.value)
