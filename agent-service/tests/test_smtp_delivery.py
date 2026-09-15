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
        assert (
            "<p>Hello HTML</p>"
            in parsed.get_body(preferencelist=("html",)).get_content()
        )


def test_plaintext_smtp_is_rejected_without_explicit_loopback_mode(
    tmp_path, smtp_server
):
    from fmg_agent.email.smtp import deliver

    config = configuration(tmp_path, smtp_server)
    config.smtp_allow_insecure_loopback = False
    assert deliver(config, {}, "test")["state"] == "failed"
    assert smtp_server.messages == []
