import os
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from app.integrations.errors import PermanentIntegrationError, TransientIntegrationError
from app.integrations.filesystem import FilesystemArtifactStore


def test_filesystem_put_json_uses_exact_key_and_deterministic_bytes(
    tmp_path: Path,
) -> None:
    job_id = UUID("12345678-1234-5678-1234-567812345678")
    store = FilesystemArtifactStore(directory=tmp_path)

    key = store.put_json(job_id, "steam-source.json", {"z": 1, "a": "游戏"})

    assert key == "acquisition/12345678-1234-5678-1234-567812345678/steam-source.json"
    assert (tmp_path / key).read_bytes() == (b'{"a":"\xe6\xb8\xb8\xe6\x88\x8f","z":1}')
    assert list((tmp_path / "acquisition" / str(job_id)).iterdir()) == [tmp_path / key]


def test_filesystem_replaces_atomically_and_removes_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    job_id = uuid4()
    store = FilesystemArtifactStore(directory=tmp_path)
    key = store.put_json(job_id, "source.json", {"version": 1})
    destination = tmp_path / key
    replacements: list[tuple[Path, Path, bytes]] = []
    real_replace = os.replace

    def recording_replace(
        source: str | os.PathLike[str], target: str | os.PathLike[str]
    ) -> None:
        source_path = Path(source)
        target_path = Path(target)
        replacements.append((source_path, target_path, source_path.read_bytes()))
        assert target_path.read_bytes() == b'{"version":1}'
        real_replace(source, target)

    monkeypatch.setattr("app.integrations.filesystem.os.replace", recording_replace)

    assert store.put_json(job_id, "source.json", {"version": 2}) == key

    assert len(replacements) == 1
    temporary, replaced, bytes_before_replace = replacements[0]
    assert temporary.parent == destination.parent
    assert temporary != destination
    assert replaced == destination
    assert bytes_before_replace == b'{"version":2}'
    assert destination.read_bytes() == b'{"version":2}'
    assert not temporary.exists()


@pytest.mark.parametrize(
    "name",
    ["", ".", "..", "../source.json", "folder/source.json", ".hidden.json"],
)
def test_filesystem_reuses_s3_artifact_name_contract(tmp_path: Path, name: str) -> None:
    with pytest.raises(PermanentIntegrationError, match="artifact_name_invalid"):
        FilesystemArtifactStore(directory=tmp_path).put_json(
            uuid4(), name, {"ok": True}
        )

    assert not (tmp_path / "acquisition").exists()


@pytest.mark.parametrize(
    ("job_id", "payload", "code"),
    [
        ("not-a-uuid", {"ok": True}, "artifact_job_id_invalid"),
        (uuid4(), {"bad": float("nan")}, "artifact_payload_invalid"),
        (uuid4(), ["not", "a", "mapping"], "artifact_payload_invalid"),
    ],
)
def test_filesystem_reuses_s3_job_and_json_contract(
    tmp_path: Path, job_id: object, payload: object, code: str
) -> None:
    with pytest.raises(PermanentIntegrationError, match=code):
        FilesystemArtifactStore(directory=tmp_path).put_json(  # type: ignore[arg-type]
            job_id, "source.json", payload
        )

    assert not (tmp_path / "acquisition").exists()


def test_filesystem_rejects_oversized_json_before_creating_directories(
    tmp_path: Path,
) -> None:
    with pytest.raises(PermanentIntegrationError, match="artifact_payload_too_large"):
        FilesystemArtifactStore(directory=tmp_path, max_json_bytes=10).put_json(
            uuid4(), "source.json", {"data": "too long"}
        )

    assert not (tmp_path / "acquisition").exists()


def test_filesystem_requires_an_absolute_directory() -> None:
    with pytest.raises(
        PermanentIntegrationError, match="artifact_configuration_invalid"
    ):
        FilesystemArtifactStore(directory=Path("relative/artifacts"))


def test_filesystem_write_failure_is_safe_transient_and_cleans_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    secret = "filesystem-secret-canary"

    def fail_replace(*_args: object) -> None:
        raise OSError(f"private path detail {secret}")

    monkeypatch.setattr("app.integrations.filesystem.os.replace", fail_replace)
    with pytest.raises(
        TransientIntegrationError, match="artifact_unavailable"
    ) as caught:
        FilesystemArtifactStore(directory=tmp_path).put_json(
            uuid4(), "source.json", {"private": secret}
        )

    assert secret not in f"{caught.value!s}{caught.value!r}{caplog.text}"
    assert list(tmp_path.rglob("*.*")) == []
