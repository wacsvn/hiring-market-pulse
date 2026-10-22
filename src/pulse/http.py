"""HTTP requests that retry temporary failures (timeouts, 429, 5xx) with backoff."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx

RETRY_STATUS = {429, 500, 502, 503, 504}


def request(
    http: httpx.Client,
    method: str,
    url: str,
    *,
    attempts: int = 4,
    base_delay: float = 2.0,
    sleep: Callable[[float], None] = time.sleep,
    **kwargs: Any,
) -> httpx.Response:
    """Send a request; on a temporary failure wait base_delay * 2^n seconds and try again.

    Raises the last error once `attempts` are used up. Other 4xx errors are raised at once,
    since repeating a bad request won't fix it.
    """
    for attempt in range(1, attempts + 1):
        try:
            resp = http.request(method, url, **kwargs)
            if resp.status_code not in RETRY_STATUS or attempt == attempts:
                resp.raise_for_status()
                return resp
        except httpx.TransportError:
            if attempt == attempts:
                raise
        sleep(base_delay * 2 ** (attempt - 1))
    raise AssertionError("unreachable")
