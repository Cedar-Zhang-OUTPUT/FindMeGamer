"""Loopback ingress forwards only API paths to one fixed internal service."""

from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit


def allowed_path(path):
    parsed = urlsplit(path)
    return (
        not parsed.scheme
        and not parsed.netloc
        and not parsed.fragment
        and parsed.path.startswith(("/api/v1/", "/api/v2/"))
    )


class Relay(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def forward(self):
        if not allowed_path(self.path) or self.headers.get("Transfer-Encoding"):
            self.send_error(400, "Fixture route rejected")
            return
        size = int(self.headers.get("Content-Length", "0"))
        if not 0 <= size <= 2_000_000:
            self.send_error(413)
            return
        headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower() not in {"host", "connection", "proxy-authorization"}
        }
        connection = HTTPConnection("api", 8000, timeout=30)
        try:
            connection.request(
                self.command, self.path, body=self.rfile.read(size), headers=headers
            )
            response = connection.getresponse()
            body = response.read(8_000_001)
            if len(body) > 8_000_000:
                raise ValueError()
            self.send_response(response.status)
            for key, value in response.getheaders():
                if key.lower() not in {
                    "connection",
                    "transfer-encoding",
                    "content-length",
                }:
                    self.send_header(key, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (OSError, ValueError):
            self.send_error(502, "Fixture service unavailable")
        finally:
            connection.close()

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = forward


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8000), Relay).serve_forever()
