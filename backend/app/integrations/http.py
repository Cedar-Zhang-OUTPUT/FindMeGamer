from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import httpx


class ResponseTooLarge(Exception):
    pass


class InvalidContentLength(Exception):
    pass


@contextmanager
def streaming_response(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    timeout: httpx.Timeout,
    params: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    json: Any = None,
    auth: httpx.Auth | tuple[str, str] | None = None,
    follow_redirects: bool = False,
) -> Iterator[httpx.Response]:
    request = client.build_request(
        method,
        url,
        params=params,
        headers=headers,
        json=json,
        timeout=timeout,
    )
    response = client.send(
        request,
        stream=True,
        auth=auth,
        follow_redirects=follow_redirects,
    )
    try:
        yield response
    finally:
        response.close()


def read_bounded_bytes(response: httpx.Response, *, max_bytes: int) -> bytes:
    if max_bytes < 1:
        raise ValueError("max_bytes must be positive")
    declared_lengths = response.headers.get_list("content-length")
    if declared_lengths:
        if len(declared_lengths) != 1:
            raise InvalidContentLength
        declared = declared_lengths[0]
        if not declared.isascii() or not declared.isdecimal():
            raise InvalidContentLength
        normalized = declared.lstrip("0") or "0"
        maximum = str(max_bytes)
        if len(normalized) > len(maximum) or (
            len(normalized) == len(maximum) and normalized > maximum
        ):
            raise ResponseTooLarge

    body = bytearray()
    for chunk in response.iter_bytes():
        if len(chunk) > max_bytes - len(body):
            raise ResponseTooLarge
        body.extend(chunk)
    return bytes(body)
