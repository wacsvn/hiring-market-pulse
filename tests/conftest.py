from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from pulse.sources.bls_jolts import BLSClient
from pulse.sources.hn_algolia import BASE_URL, HNClient

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text())


def hn_transport(
    mutate_item: Callable[[dict[str, Any]], None] | None = None,
) -> httpx.MockTransport:
    """Serves recorded HN responses; `mutate_item` lets a test corrupt a thread payload."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/search_by_date"):
            return httpx.Response(200, json=load_fixture("hn_search.json"))
        if "/items/" in path:
            item_id = path.rsplit("/", 1)[-1]
            f = FIXTURES / f"hn_item_{item_id}.json"
            if not f.exists():
                return httpx.Response(404, json={"error": "not found"})
            item = json.loads(f.read_text())
            if mutate_item:
                mutate_item(item)
            return httpx.Response(200, json=item)
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def bls_transport(body: dict[str, Any] | None = None) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json=body if body is not None else load_fixture("bls_jolts.json")
        )

    return httpx.MockTransport(handler)


@pytest.fixture
def hn_client() -> HNClient:
    return HNClient(httpx.Client(base_url=BASE_URL, transport=hn_transport()))


@pytest.fixture
def bls_client() -> BLSClient:
    return BLSClient(
        httpx.Client(base_url="https://api.bls.gov/publicAPI/v1", transport=bls_transport()),
        api_key="",
    )
