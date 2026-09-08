"""Isolated Settings fixture. Never import this in a production entry point."""
import json
import os
from pathlib import Path
import sys

import httpx

from app.integrations.connection_probe import ProductionConnectionProbe
from app.outreach.smtp import SMTPGateway
from capture_smtp import CaptureSMTPConnection

ORIGIN = 'https://settings.integration.invalid'
SUCCESS_KEYS = {
    'youtube': 'synthetic-youtube-key',
    'deepseek': 'synthetic-deepseek-key',
    'google_ai': 'synthetic-google-ai-key',
    'x': 'synthetic-x-key',
}
ROUTES = {
    '/youtube/v3/channels?part=id&id=UC_x5XG1OV2P6uZZ5FSM9Ttw': ('youtube', 'x-goog-api-key'),
    '/deepseek/models': ('deepseek', 'authorization'),
    '/google-ai/v1beta/models': ('google_ai', 'x-goog-api-key'),
    '/x/2/usage/tweets?days=1': ('x', 'authorization'),
}


def strict_handler(request: httpx.Request) -> httpx.Response:
    """Match full destination, method, query and credential header; no fallback."""
    route = ROUTES.get(request.url.raw_path.decode('ascii'))
    if (request.method != 'GET' or request.url.scheme != 'https'
            or request.url.host != 'settings.integration.invalid'
            or request.url.port not in (None, 443) or request.url.userinfo
            or request.url.fragment or route is None or request.content):
        raise httpx.ConnectError('Fixture request rejected', request=request)
    service, header = route
    other_header = 'authorization' if header == 'x-goog-api-key' else 'x-goog-api-key'
    values = request.headers.get_list(header)
    if (len(values) != 1 or other_header in request.headers
            or request.headers.get('host') != 'settings.integration.invalid'
            or 'cookie' in request.headers):
        raise httpx.ConnectError('Fixture request rejected', request=request)
    expected = SUCCESS_KEYS[service]
    if header == 'authorization':
        expected = f'Bearer {expected}'
    return httpx.Response(200 if values[0] == expected else 401, json={})


def make_probe(client: httpx.Client) -> ProductionConnectionProbe:
    return ProductionConnectionProbe(
        deepseek_base_url=f'{ORIGIN}/deepseek',
        youtube_base_url=f'{ORIGIN}/youtube/v3',
        google_ai_base_url=f'{ORIGIN}/google-ai/v1beta/models',
        x_base_url=f'{ORIGIN}/x/2',
        http_client=client,
    )


def transport_event(event: str) -> None:
    with (Path(os.environ['FAKE_STATE_DIR']) / 'smtp-transport.log').open('a') as stream:
        stream.write(event + '\n')


class SettingsCaptureConnection(CaptureSMTPConnection):
    def starttls(self, *, context) -> None:
        transport_event('starttls')
        super().starttls(context=context)


def capture_gateway() -> SMTPGateway:
    def resolve(host, port):
        if host != 'smtp.integration.invalid' or port not in (465, 587):
            raise AssertionError('Unexpected fixture SMTP destination')
        return ('8.8.8.8',)  # Only SSRF validation input; factory never opens a socket.

    def factory(host, address, port, encryption, context, timeout):
        if (host != 'smtp.integration.invalid' or address != '8.8.8.8'
                or (port, encryption) not in ((465, 'tls'), (587, 'starttls'))):
            raise AssertionError('Unexpected fixture SMTP transport')
        transport_event(f'connect {port} {encryption}')
        return SettingsCaptureConnection()

    return SMTPGateway(resolver=resolve, factory=factory)


def main() -> None:
    if sys.argv[1:] != ['serve']:
        raise SystemExit('Only serve is supported; no initialization or seeding.')
    from app.core.security import hash_workspace_key

    private = json.loads(Path('/private/client.json').read_text())
    os.environ['WORKSPACE_ACCESS_KEY_HASH'] = hash_workspace_key(private['workspace_key'])
    del private
    # The unchanged backend reads MASTER_KEY_FILE from the existing private mount.
    from app.main import create_app
    import uvicorn

    with httpx.Client(transport=httpx.MockTransport(strict_handler),
                      trust_env=False, follow_redirects=False) as client:
        app = create_app(connection_probe=make_probe(client), smtp_gateway=capture_gateway())
        uvicorn.run(app, host='0.0.0.0', port=8000, proxy_headers=False, access_log=False)


if __name__ == '__main__':
    sys.path.insert(0, '/app')
    main()
