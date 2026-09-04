import httpx

from app.integrations.connection_probe import ProductionConnectionProbe


def test_deepseek_probe_uses_models_endpoint_and_bearer_secret() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"data": []})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    probe = ProductionConnectionProbe(
        deepseek_base_url="https://api.deepseek.com",
        youtube_base_url="https://www.googleapis.com/youtube/v3",
        google_ai_base_url="https://generativelanguage.googleapis.com/v1beta/models",
        http_client=client,
    )

    assert probe.test_connection("deepseek", "deepseek-canary") is True
    assert len(seen) == 1
    assert seen[0].url == "https://api.deepseek.com/models"
    assert seen[0].headers["authorization"] == "Bearer deepseek-canary"
    assert "deepseek-canary" not in str(seen[0].url)


def test_youtube_probe_uses_header_without_putting_secret_in_url() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"items": [{"id": "UC_x5XG1OV2P6uZZ5FSM9Ttw"}]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    probe = ProductionConnectionProbe(
        deepseek_base_url="https://api.deepseek.com",
        youtube_base_url="https://www.googleapis.com/youtube/v3",
        google_ai_base_url="https://generativelanguage.googleapis.com/v1beta/models",
        http_client=client,
    )

    assert probe.test_connection("youtube", "youtube-canary") is True
    assert len(seen) == 1
    assert seen[0].url.path == "/youtube/v3/channels"
    assert seen[0].url.params["part"] == "id"
    assert seen[0].headers.get_list("x-goog-api-key") == ["youtube-canary"]
    assert "youtube-canary" not in str(seen[0].url)


def test_google_ai_probe_uses_models_endpoint_and_header_only_secret() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"models": []})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    probe = ProductionConnectionProbe(
        deepseek_base_url="https://api.deepseek.com",
        youtube_base_url="https://www.googleapis.com/youtube/v3",
        google_ai_base_url="https://generativelanguage.googleapis.com/v1beta/models",
        http_client=client,
    )

    assert probe.test_connection("google_ai", "google-ai-canary") is True
    assert len(seen) == 1
    assert seen[0].url == "https://generativelanguage.googleapis.com/v1beta/models"
    assert seen[0].headers.get_list("x-goog-api-key") == ["google-ai-canary"]
    assert "google-ai-canary" not in str(seen[0].url)


def test_probe_returns_failure_for_provider_rejection_or_unsupported_service() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(lambda _request: httpx.Response(401))
    )
    probe = ProductionConnectionProbe(
        deepseek_base_url="https://api.deepseek.com",
        youtube_base_url="https://www.googleapis.com/youtube/v3",
        google_ai_base_url="https://generativelanguage.googleapis.com/v1beta/models",
        http_client=client,
    )

    assert probe.test_connection("deepseek", "rejected") is False
    assert probe.test_connection("youtube", "rejected") is False
    assert probe.test_connection("google_ai", "rejected") is False
    assert probe.test_connection("steam", "unused-in-v1") is False


def test_probe_sanitizes_transport_failure_to_false() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("provider unavailable")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    probe = ProductionConnectionProbe(
        deepseek_base_url="https://api.deepseek.com",
        youtube_base_url="https://www.googleapis.com/youtube/v3",
        google_ai_base_url="https://generativelanguage.googleapis.com/v1beta/models",
        http_client=client,
    )

    assert probe.test_connection("deepseek", "secret") is False
