from pathlib import Path

from app import run


BACKEND_ROOT = Path(__file__).resolve().parents[2]


def test_production_entrypoint_disables_upstream_proxy_and_access_log_processing(
    monkeypatch,
) -> None:
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def record_run(*args: object, **kwargs: object) -> None:
        calls.append((args, kwargs))

    monkeypatch.setattr(run.uvicorn, "run", record_run)

    run.main()

    assert calls == [
        (
            ("app.main:app",),
            {
                "host": "0.0.0.0",
                "port": 8000,
                "proxy_headers": False,
                "access_log": False,
            },
        )
    ]


def test_docker_cmd_uses_authoritative_production_entrypoint() -> None:
    dockerfile_lines = [
        line.strip()
        for line in (BACKEND_ROOT / "Dockerfile").read_text().splitlines()
        if line.strip().startswith("CMD ")
    ]

    assert dockerfile_lines == ['CMD ["python", "-m", "app.run"]']
