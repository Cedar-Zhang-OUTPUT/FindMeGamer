"""Tests use accepted backend code and temporary capture state, never services."""
from email.message import EmailMessage
import os
from pathlib import Path
import sys
from unittest.mock import patch

import httpx
import pytest

STABLE = Path('/tmp/fmg-frontend-stable.bpM1DM/repo')
sys.path[:0] = [str(STABLE / 'backend'), str(STABLE / 'integration/runtime')]

from settings_runtime import make_probe, strict_handler, capture_gateway, SUCCESS_KEYS
from app.outreach.smtp import SMTPConfig, SMTPTransientError
from app.integrations.connection_probe import ProductionConnectionProbe


@pytest.mark.parametrize('service', ['youtube', 'deepseek', 'google_ai', 'x'])
def test_real_probe_shapes_and_rejects_credentials(service):
    with patch('socket.getaddrinfo', side_effect=AssertionError('No DNS')), patch(
        'socket.socket.connect', side_effect=AssertionError('No socket')
    ):
        with httpx.Client(transport=httpx.MockTransport(strict_handler)) as client:
            probe = make_probe(client)
            assert probe.test_connection(service, SUCCESS_KEYS[service])
            assert not probe.test_connection(service, 'synthetic-rejected-key')
            assert not probe.test_connection('steam', 'synthetic-steam-key')


@pytest.mark.parametrize('url,method,headers', [
    ('https://real-provider.invalid/deepseek/models', 'GET', {}),
    ('https://settings.integration.invalid/deepseek/models?extra=1', 'GET', {}),
    ('https://settings.integration.invalid/deepseek/models', 'POST', {}),
    ('https://settings.integration.invalid/deepseek/models', 'GET', {'X-Goog-Api-Key': 'synthetic-youtube-key'}),
])
def test_unexpected_request_fails_closed(url, method, headers):
    with pytest.raises(httpx.ConnectError, match='Fixture request rejected'):
        strict_handler(httpx.Request(method, url, headers=headers))


def test_real_probe_forbidden_origin_returns_failure_without_network():
    with patch('socket.getaddrinfo', side_effect=AssertionError('No DNS')), patch(
        'socket.socket.connect', side_effect=AssertionError('No socket')
    ), httpx.Client(transport=httpx.MockTransport(strict_handler)) as client:
        probe = ProductionConnectionProbe(
            deepseek_base_url='https://unapproved.invalid/deepseek',
            youtube_base_url='https://settings.integration.invalid/youtube/v3',
            google_ai_base_url='https://settings.integration.invalid/google-ai/v1beta/models',
            http_client=client,
        )
        assert not probe.test_connection('deepseek', SUCCESS_KEYS['deepseek'])


@pytest.mark.parametrize('port,encryption', [(465, 'tls'), (587, 'starttls')])
def test_real_smtp_probe_zero_send_one(tmp_path, port, encryption):
    config = SMTPConfig('smtp.integration.invalid', port, encryption,
                        'sender@example.com', 'synthetic-smtp-integration-key',
                        'Settings Fixture', 'sender@example.com')
    message = EmailMessage()
    message['From'] = 'sender@example.com'
    message['To'] = 'company@example.com'
    message.set_content('Synthetic Settings test email.')
    with patch.dict(os.environ, {'FAKE_STATE_DIR': str(tmp_path)}), patch(
        'socket.getaddrinfo', side_effect=AssertionError('No DNS')
    ), patch('socket.socket.connect', side_effect=AssertionError('No socket')):
        gateway = capture_gateway()
        gateway.probe(config)
        assert list(tmp_path.glob('smtp-*.eml')) == []
        assert gateway.send(config, message).accepted_recipients == 1
    assert len(list(tmp_path.glob('smtp-*.eml'))) == 1
    assert (tmp_path / 'calls.log').read_text() == 'smtp send_message\n'
    events = (tmp_path / 'smtp-transport.log').read_text()
    assert events.splitlines().count('starttls') == (2 if encryption == 'starttls' else 0)
    assert events.count(f'connect {port} {encryption}\n') == 2


def test_smtp_rejects_nonfixture_host():
    config = SMTPConfig('smtp.example.com', 465, 'tls', 'sender@example.com',
                        'synthetic-smtp-integration-key', 'Fixture', '')
    with pytest.raises(SMTPTransientError):
        capture_gateway().probe(config)
