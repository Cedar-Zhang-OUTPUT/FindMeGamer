"""Keep HTTP client's diagnostic logs from exposing query-string credentials."""

import logging
import re


class CredentialFilter(logging.Filter):
    def filter(self, record):
        message = record.getMessage()
        message = re.sub(
            r"([?&](?:key|access_token|oauth_token|token)=)[^&\s\"\']+",
            r"\1[REDACTED]",
            message,
            flags=re.IGNORECASE,
        )
        message = re.sub(
            r"Bearer\s+[^\s\"\',)]+", "Bearer [REDACTED]", message, flags=re.IGNORECASE
        )
        record.msg = message
        record.args = ()
        return True


def protect_http_logs():
    for name in (
        "httpx",
        "httpcore.connection",
        "httpcore.http11",
        "httpcore.http2",
        "httpcore.proxy",
        "httpcore.socks",
    ):
        logger = logging.getLogger(name)
        if not any(
            isinstance(existing, CredentialFilter) for existing in logger.filters
        ):
            logger.addFilter(CredentialFilter())
