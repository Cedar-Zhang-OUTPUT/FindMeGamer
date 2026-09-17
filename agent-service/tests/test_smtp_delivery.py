from email import policy
from email.parser import BytesParser
import socketserver
from threading import Thread

import pytest


@pytest.fixture
def smtp_server():
    class Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True

    class Handler(socketserver.StreamRequestHandler):
        def reply(self, line):
            self.wfile.write(line + b"\r\n")
            self.wfile.flush()

        def handle(self):
            self.reply(b"220 local-test ESMTP")
            while True:
                line = self.rfile.readline()
                if not line:
                    return
                command = line.split(b" ", 1)[0].strip().upper()
                if command in {b"EHLO", b"HELO", b"MAIL", b"RSET"}:
                    self.reply(b"250 OK")
                elif command == b"RCPT":
                    self.reply(
                        b"550 rejected" if self.server.mode == "reject" else b"250 OK"
                    )
                elif command == b"DATA":
                    self.reply(b"354 send data")
                    body = bytearray()
                    while True:
                        part = self.rfile.readline()
                        if not part or part == b".\r\n":
                            break
                        body.extend(part[1:] if part.startswith(b"..") else part)
                    self.server.messages.append(bytes(body))
                    if self.server.mode == "unknown":
                        return
                    self.reply(b"250 accepted")
                elif command == b"QUIT":
                    self.reply(b"221 bye")
                    return
                else:
                    self.reply(b"502 unsupported")

    server = Server(("127.0.0.1", 0), Handler)
    server.mode = "sent"
    server.messages = []
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def configuration(tmp_path, smtp_server):
    from fmg_agent.config import Settings

    return Settings(
        database_url=f"sqlite:///{tmp_path / 'smtp.sqlite'}",
        smtp_host="127.0.0.1",
        smtp_port=smtp_server.server_address[1],
        smtp_encryption="none",
        smtp_allow_insecure_loopback=True,
        smtp_from="publisher@example.com",
    )


def test_test_recipient_allowlist_blocks_before_network(tmp_path, smtp_server):
    from fmg_agent.email.smtp import deliver
    config = configuration(tmp_path, smtp_server)
    config.smtp_allowed_recipients = ["test@example.com"]
    result = deliver(config, {"to": "outside@example.com"}, "blocked")
    assert result == {"state": "failed", "code": "smtp_recipient_not_allowed"}
    assert smtp_server.messages == []


@pytest.mark.parametrize(
    "mode,state,count",
    [("sent", "sent", 1), ("reject", "failed", 0), ("unknown", "unknown", 1)],
)
def test_actual_smtp_delivery_and_ambiguous_accept(
    tmp_path, smtp_server, mode, state, count
):
    from fmg_agent.email.smtp import deliver

    smtp_server.mode = mode
    message = {
        "from": "publisher@example.com",
        "to": "creator@example.com",
        "subject": "Test",
        "text": "Hello text",
        "html": "<p>Hello HTML</p>",
    }
    outcome = deliver(configuration(tmp_path, smtp_server), message, "test-id")
    assert outcome["state"] == state
    assert len(smtp_server.messages) == count
    if count:
        parsed = BytesParser(policy=policy.default).parsebytes(smtp_server.messages[0])
        assert parsed["To"] == "creator@example.com"
        assert parsed["From"] == "publisher@example.com"
        assert parsed["Message-ID"] == "<fmg-test-id@example.com>"
        assert (
            parsed.get_body(preferencelist=("plain",)).get_content().strip()
            == "Hello text"
        )
        assert parsed.get_content_type() == "text/plain"
        assert not parsed.is_multipart()


def test_plaintext_smtp_is_rejected_without_explicit_loopback_mode(
    tmp_path, smtp_server
):
    from fmg_agent.email.smtp import deliver

    config = configuration(tmp_path, smtp_server)
    config.smtp_allow_insecure_loopback = False
    assert deliver(config, {}, "test")["state"] == "failed"
    assert smtp_server.messages == []


def test_liminal_signature_embedded_without_remote_images(tmp_path, smtp_server):
    from fmg_agent.email.smtp import deliver
    from fmg_agent.email.templates import get_template, render_template
    from test_liminal_template import values
    message = render_template(get_template("liminal-outreach"), values())
    message.update({"from": "publisher@example.com", "to": "creator@example.com"})
    assert deliver(configuration(tmp_path, smtp_server), message, "signature-test")["state"] == "sent"
    parsed = BytesParser(policy=policy.default).parsebytes(smtp_server.messages[0])
    assert parsed.get_content_type() == "multipart/alternative"
    assert "Kind regards," in parsed.get_body(preferencelist=("plain",)).get_content()
    html = parsed.get_body(preferencelist=("html",)).get_content()
    assert 'src="cid:ontology-play-signature"' in html
    pictures = [p for p in parsed.walk() if p.get_content_type() == "image/png"]
    assert len(pictures) == 1
    assert pictures[0]["Content-ID"] == "<ontology-play-signature>"
    assert pictures[0].get_content_disposition() == "inline"
    assert pictures[0].get_payload(decode=True).startswith(b"\x89PNG")
