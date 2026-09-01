import logging
from typing import Any
from uuid import UUID, uuid4

import boto3
from botocore.exceptions import ClientError, EndpointConnectionError
from botocore.stub import Stubber
import pytest

from app.integrations.errors import PermanentIntegrationError, TransientIntegrationError
from app.integrations.s3 import (
    ARTIFACT_RETENTION_TAGGING,
    MAX_ARTIFACT_JSON_BYTES,
    S3ArtifactStore,
)


class RecordingS3Client:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.error: Exception | None = None
        self.closed = False

    def put_object(self, **kwargs: Any) -> dict[str, str]:
        if self.error is not None:
            raise self.error
        self.calls.append(kwargs)
        return {"ETag": "test-etag"}

    def close(self) -> None:
        self.closed = True


def test_s3_put_json_uses_exact_deterministic_bytes_key_content_type_and_tag() -> None:
    client = RecordingS3Client()
    job_id = UUID("12345678-1234-5678-1234-567812345678")
    store = S3ArtifactStore(bucket="analysis-artifacts", s3_client=client)

    key = store.put_json(job_id, "steam-source.json", {"z": 1, "a": "游戏"})

    assert key == "acquisition/12345678-1234-5678-1234-567812345678/steam-source.json"
    assert client.calls == [
        {
            "Bucket": "analysis-artifacts",
            "Key": key,
            "Body": b'{"a":"\xe6\xb8\xb8\xe6\x88\x8f","z":1}',
            "ContentType": "application/json",
            "Tagging": ARTIFACT_RETENTION_TAGGING,
        }
    ]


@pytest.mark.parametrize(
    "name",
    [
        "",
        ".",
        "..",
        "../source.json",
        "folder/source.json",
        "folder\\source.json",
        ".hidden.json",
        "trailing.",
        "source\x00.json",
        "Ｓource.json",
        "x" * 129,
    ],
)
def test_s3_rejects_unsafe_artifact_name_before_client_call(name: str) -> None:
    client = RecordingS3Client()

    with pytest.raises(PermanentIntegrationError, match="artifact_name_invalid"):
        S3ArtifactStore(bucket="analysis-artifacts", s3_client=client).put_json(
            uuid4(), name, {"ok": True}
        )

    assert client.calls == []


def test_s3_rejects_invalid_job_id_before_client_call() -> None:
    client = RecordingS3Client()

    with pytest.raises(PermanentIntegrationError, match="artifact_job_id_invalid"):
        S3ArtifactStore(bucket="analysis-artifacts", s3_client=client).put_json(
            "not-a-uuid", "source.json", {"ok": True}  # type: ignore[arg-type]
        )

    assert client.calls == []


@pytest.mark.parametrize(
    "payload",
    [
        {"bad": float("nan")},
        {"bad": object()},
        ["not", "a", "mapping"],
    ],
)
def test_s3_rejects_non_json_or_non_mapping_payload(payload: object) -> None:
    client = RecordingS3Client()

    with pytest.raises(PermanentIntegrationError, match="artifact_payload_invalid"):
        S3ArtifactStore(bucket="analysis-artifacts", s3_client=client).put_json(
            uuid4(), "source.json", payload  # type: ignore[arg-type]
        )

    assert client.calls == []


def test_s3_rejects_oversized_json_before_client_call() -> None:
    client = RecordingS3Client()

    with pytest.raises(PermanentIntegrationError, match="artifact_payload_too_large"):
        S3ArtifactStore(bucket="analysis-artifacts", s3_client=client).put_json(
            uuid4(), "source.json", {"data": "x" * MAX_ARTIFACT_JSON_BYTES}
        )

    assert client.calls == []


def test_s3_reuses_injected_client_and_does_not_close_it() -> None:
    client = RecordingS3Client()
    store = S3ArtifactStore(bucket="analysis-artifacts", s3_client=client)

    store.put_json(uuid4(), "one.json", {"value": 1})
    store.put_json(uuid4(), "two.json", {"value": 2})
    store.close()

    assert len(client.calls) == 2
    assert client.closed is False


class RecordingSession:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.client_instance = RecordingS3Client()

    def client(self, service_name: str, **kwargs: Any) -> RecordingS3Client:
        self.calls.append({"service_name": service_name, **kwargs})
        return self.client_instance


def test_s3_owned_client_uses_explicit_timeouts_bounded_retries_and_closes() -> None:
    session = RecordingSession()
    store = S3ArtifactStore(
        bucket="analysis-artifacts",
        region="us-west-2",
        endpoint_url="http://localhost:4566",
        session=session,  # type: ignore[arg-type]
    )

    store.put_json(uuid4(), "source.json", {"ok": True})
    store.close()

    assert len(session.calls) == 1
    call = session.calls[0]
    assert call["service_name"] == "s3"
    assert call["region_name"] == "us-west-2"
    assert call["endpoint_url"] == "http://localhost:4566"
    config = call["config"]
    assert config.connect_timeout == 5.0
    assert config.read_timeout == 20.0
    assert config.retries["total_max_attempts"] == 3
    assert config.retries["mode"] == "standard"
    assert session.client_instance.closed is True


def _stubbed_client():
    return boto3.client(
        "s3",
        region_name="us-east-1",
        endpoint_url="http://localhost:4566",
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )


@pytest.mark.parametrize(
    ("code", "status"),
    [("SlowDown", 503), ("RequestTimeout", 400), ("InternalError", 500)],
)
def test_s3_stubber_classifies_retryable_service_errors_as_transient(
    code: str, status: int
) -> None:
    client = _stubbed_client()
    job_id = UUID("12345678-1234-5678-1234-567812345678")
    key = f"acquisition/{job_id}/source.json"
    expected = {
        "Bucket": "analysis-artifacts",
        "Key": key,
        "Body": b'{"ok":true}',
        "ContentType": "application/json",
        "Tagging": ARTIFACT_RETENTION_TAGGING,
    }
    with Stubber(client) as stubber:
        stubber.add_client_error(
            "put_object",
            service_error_code=code,
            service_message="signed-url?secret=canary",
            http_status_code=status,
            expected_params=expected,
        )
        with pytest.raises(TransientIntegrationError, match="s3_unavailable"):
            S3ArtifactStore(bucket="analysis-artifacts", s3_client=client).put_json(
                job_id, "source.json", {"ok": True}
            )


@pytest.mark.parametrize(
    ("code", "status"),
    [("AccessDenied", 403), ("NoSuchBucket", 404), ("InvalidArgument", 400)],
)
def test_s3_stubber_classifies_deterministic_service_errors_as_permanent(
    code: str, status: int
) -> None:
    client = _stubbed_client()
    with Stubber(client) as stubber:
        stubber.add_client_error(
            "put_object",
            service_error_code=code,
            service_message="secret response body",
            http_status_code=status,
        )
        with pytest.raises(PermanentIntegrationError, match="s3_request_rejected"):
            S3ArtifactStore(bucket="analysis-artifacts", s3_client=client).put_json(
                uuid4(), "source.json", {"ok": True}
            )


def test_s3_endpoint_failure_is_transient_and_redacted(caplog) -> None:
    client = RecordingS3Client()
    secret = "s3-endpoint-secret-canary"
    client.error = EndpointConnectionError(endpoint_url=f"https://s3.example/{secret}")

    with caplog.at_level(logging.DEBUG), pytest.raises(
        TransientIntegrationError, match="s3_unavailable"
    ) as caught:
        S3ArtifactStore(bucket="analysis-artifacts", s3_client=client).put_json(
            uuid4(), "source.json", {"private": secret}
        )

    assert secret not in f"{caught.value!s}{caught.value!r}{caplog.text}"


def test_s3_rejects_unsafe_endpoint_and_bucket_configuration() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        S3ArtifactStore(
            bucket="analysis-artifacts", endpoint_url="http://s3.example.com"
        )
    with pytest.raises(PermanentIntegrationError, match="s3_configuration_invalid"):
        S3ArtifactStore(bucket="Bad_Bucket", s3_client=RecordingS3Client())
