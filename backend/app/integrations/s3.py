from collections.abc import Mapping
from ipaddress import ip_address
import json
import math
import re
from typing import Any, Protocol
from uuid import UUID

import boto3
from botocore.config import Config
from botocore.exceptions import (
    BotoCoreError,
    ClientError,
    ConnectTimeoutError,
    ConnectionClosedError,
    EndpointConnectionError,
    HTTPClientError,
    NoCredentialsError,
    NoRegionError,
    ParamValidationError,
    PartialCredentialsError,
    ReadTimeoutError,
)

from app.core.config import validate_external_base_url
from app.integrations.errors import PermanentIntegrationError, TransientIntegrationError

ARTIFACT_PREFIX = "acquisition"
ARTIFACT_RETENTION_TAGGING = "retention=temporary-analysis-30d"
MAX_ARTIFACT_JSON_BYTES = 5_000_000
S3_CLIENT_CONFIG = Config(
    connect_timeout=5.0,
    read_timeout=20.0,
    retries={"total_max_attempts": 3, "mode": "standard"},
    max_pool_connections=20,
)
_artifact_name = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,126}[A-Za-z0-9])?$")
_bucket_name = re.compile(
    r"^(?!xn--)(?!sthree-)(?!amzn-s3-demo-)[a-z0-9]" r"(?:[a-z0-9.-]{1,61}[a-z0-9])?$"
)
_region_name = re.compile(r"^[a-z]{2}(?:-gov)?-[a-z]+-\d$")
_TRANSIENT_CODES = frozenset(
    {
        "SlowDown",
        "RequestTimeout",
        "RequestTimeoutException",
        "Throttling",
        "ThrottlingException",
        "InternalError",
        "ServiceUnavailable",
    }
)


class S3Client(Protocol):
    def put_object(self, **kwargs: Any) -> object: ...

    def close(self) -> None: ...


class S3Session(Protocol):
    def client(self, service_name: str, **kwargs: Any) -> S3Client: ...


class S3ArtifactStore:
    """Store temporary JSON under the lifecycle prefix using bucket encryption.

    The existing bucket's default encryption remains authoritative so this client
    is compatible with both AWS S3 and the configured S3-compatible service.
    """

    def __init__(
        self,
        *,
        bucket: str,
        region: str = "us-east-1",
        endpoint_url: str | None = None,
        s3_client: S3Client | None = None,
        session: S3Session | None = None,
        max_json_bytes: int = MAX_ARTIFACT_JSON_BYTES,
    ) -> None:
        _validate_configuration(bucket, region, max_json_bytes)
        self._bucket = bucket
        self._max_json_bytes = max_json_bytes
        self._owns_client = s3_client is None
        if s3_client is not None:
            self._client = s3_client
            return
        validated_endpoint = (
            validate_external_base_url(endpoint_url)
            if endpoint_url is not None
            else None
        )
        client_session = session or boto3.Session()
        try:
            self._client = client_session.client(
                "s3",
                region_name=region,
                endpoint_url=validated_endpoint,
                config=S3_CLIENT_CONFIG,
            )
        except (
            NoCredentialsError,
            PartialCredentialsError,
            NoRegionError,
            ParamValidationError,
        ):
            raise PermanentIntegrationError("s3_configuration_invalid") from None
        except (
            EndpointConnectionError,
            ConnectTimeoutError,
            ReadTimeoutError,
            ConnectionClosedError,
            HTTPClientError,
        ):
            raise TransientIntegrationError("s3_unavailable") from None
        except BotoCoreError:
            raise PermanentIntegrationError("s3_configuration_invalid") from None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "S3ArtifactStore":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def put_json(
        self,
        job_id: UUID,
        name: str,
        payload: Mapping[str, Any],
    ) -> str:
        if not isinstance(job_id, UUID) or job_id.int == 0:
            raise PermanentIntegrationError("artifact_job_id_invalid")
        _validate_artifact_name(name)
        body = _serialize_payload(payload, max_bytes=self._max_json_bytes)
        key = f"{ARTIFACT_PREFIX}/{job_id}/{name}"
        try:
            self._client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=body,
                ContentType="application/json",
                Tagging=ARTIFACT_RETENTION_TAGGING,
            )
        except ClientError as error:
            _raise_client_error(error)
        except (
            EndpointConnectionError,
            ConnectTimeoutError,
            ReadTimeoutError,
            ConnectionClosedError,
            HTTPClientError,
        ):
            raise TransientIntegrationError("s3_unavailable") from None
        except (
            NoCredentialsError,
            PartialCredentialsError,
            NoRegionError,
            ParamValidationError,
        ):
            raise PermanentIntegrationError("s3_configuration_invalid") from None
        except BotoCoreError:
            raise PermanentIntegrationError("s3_request_rejected") from None
        return key


def _validate_configuration(bucket: str, region: str, max_json_bytes: int) -> None:
    if (
        not isinstance(bucket, str)
        or not _bucket_name.fullmatch(bucket)
        or ".." in bucket
        or ".-" in bucket
        or "-." in bucket
        or not isinstance(region, str)
        or not _region_name.fullmatch(region)
        or isinstance(max_json_bytes, bool)
        or not isinstance(max_json_bytes, int)
        or not 1 <= max_json_bytes <= 100_000_000
    ):
        raise PermanentIntegrationError("s3_configuration_invalid")
    try:
        ip_address(bucket)
    except ValueError:
        return
    raise PermanentIntegrationError("s3_configuration_invalid")


def _validate_artifact_name(name: object) -> None:
    if (
        not isinstance(name, str)
        or not name.isascii()
        or not _artifact_name.fullmatch(name)
        or ".." in name
    ):
        raise PermanentIntegrationError("artifact_name_invalid")


def _serialize_payload(payload: object, *, max_bytes: int) -> bytes:
    if not isinstance(payload, Mapping):
        raise PermanentIntegrationError("artifact_payload_invalid")
    try:
        normalized = _strict_json_value(payload, depth=0)
        encoded = json.dumps(
            normalized,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError):
        raise PermanentIntegrationError("artifact_payload_invalid") from None
    if len(encoded) > max_bytes:
        raise PermanentIntegrationError("artifact_payload_too_large")
    return encoded


def _strict_json_value(value: object, *, depth: int) -> object:
    if depth > 64:
        raise ValueError("JSON nesting is too deep")
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite number")
        return value
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("JSON object keys must be strings")
            result[key] = _strict_json_value(item, depth=depth + 1)
        return result
    if isinstance(value, list):
        return [_strict_json_value(item, depth=depth + 1) for item in value]
    raise TypeError("unsupported JSON value")


def _raise_client_error(error: ClientError) -> None:
    response = error.response if isinstance(error.response, dict) else {}
    error_payload = response.get("Error")
    metadata = response.get("ResponseMetadata")
    code = error_payload.get("Code") if isinstance(error_payload, dict) else None
    status = metadata.get("HTTPStatusCode") if isinstance(metadata, dict) else None
    if (
        code in _TRANSIENT_CODES
        or status == 429
        or (isinstance(status, int) and status >= 500)
    ):
        raise TransientIntegrationError("s3_unavailable") from None
    raise PermanentIntegrationError("s3_request_rejected") from None
