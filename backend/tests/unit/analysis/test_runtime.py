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


def test_production_handle_resolver_sanitizes_unexpected_dependency_failure() -> None:
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
    with pytest.raises(ChannelResolutionUnavailable) as raised:
        resolver.resolve_channel(target)
    assert "master-key" not in str(raised.value)
