from contextlib import contextmanager

from app.analysis.runtime import ProductionAnalysisRuntime, ProductionSecretProvider
from app.core.config import get_settings
from app.core.crypto import SecretCipher
from tests.unit.analysis.test_runtime import (
    ClosableGateway,
    FakePipeline,
    _store_secret,
)


def test_runtime_loads_only_existing_x_deepseek_credentials_and_owns_all_clients(
    monkeypatch,
):
    assert callable(
        getattr(ProductionAnalysisRuntime, "x_pipeline", None)
    ), "The production X pipeline entry is missing"
    ClosableGateway.instances = []
    calls = []

    class Secrets:
        def load(self, services):
            calls.append(tuple(services))
            return {name: "fixture" for name in services}

    for name in ("XCreatorGateway", "DeepSeekGateway", "S3ArtifactStore"):
        monkeypatch.setattr(f"app.analysis.runtime.{name}", ClosableGateway)
    monkeypatch.setattr("app.analysis.runtime.XCreatorAnalysisPipeline", FakePipeline)
    runtime = ProductionAnalysisRuntime(
        settings=get_settings(), session_factory=lambda: None, secret_provider=Secrets()
    )
    with runtime.x_pipeline() as pipeline:
        assert isinstance(pipeline, FakePipeline)
        assert calls == [("x", "deepseek")]
        assert len(ClosableGateway.instances) == 3
        assert all(not instance.closed for instance in ClosableGateway.instances)
    assert all(instance.closed for instance in ClosableGateway.instances)


def test_x_key_uses_existing_encrypted_service_storage_after_session_close(session):
    _store_secret(session, "x", "x-fixture")
    _store_secret(session, "deepseek", "deepseek-fixture")

    @contextmanager
    def factory():
        try:
            yield session
        finally:
            session.commit()

    def cipher():
        assert not session.in_transaction()
        return SecretCipher(bytes(range(32)))

    provider = ProductionSecretProvider(session_factory=factory, cipher_factory=cipher)
    assert provider.load(("x", "deepseek")) == {
        "x": "x-fixture",
        "deepseek": "deepseek-fixture",
    }
