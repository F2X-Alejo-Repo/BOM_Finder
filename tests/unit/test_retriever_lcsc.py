from __future__ import annotations

import httpx
import pytest

from bom_workbench.domain.value_objects import SearchKeys
from bom_workbench.infrastructure.retrievers import LcscEvidenceRetriever


def _patch_async_client(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    original_async_client = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return original_async_client(*args, **kwargs)

    monkeypatch.setattr(
        "bom_workbench.infrastructure.retrievers.lcsc.httpx.AsyncClient",
        factory,
    )


@pytest.mark.anyio
async def test_retriever_uses_lcsc_part_number_before_other_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen_urls: list[httpx.URL] = []
    seen_user_agents: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_urls.append(request.url)
        seen_user_agents.append(request.headers.get("user-agent", ""))
        return httpx.Response(200, text="part evidence", headers={"content-type": "text/html"})

    _patch_async_client(monkeypatch, handler)

    retriever = LcscEvidenceRetriever(base_url="https://example.test")
    evidence = await retriever.retrieve(
        SearchKeys(
            lcsc_part_number="C12345",
            mpn="MPN-IGNORE",
            source_url="https://example.test/source",
            category="resistor",
            footprint="0603",
            param_summary="10k",
        )
    )

    assert seen_urls == [httpx.URL("https://example.test/search?searchTerm=C12345")]
    assert len(evidence) == 1
    assert evidence[0].search_strategy == "lcsc_part_number"
    assert evidence[0].source_name == "LCSC"
    assert seen_user_agents
    assert "Mozilla/5.0" in seen_user_agents[0]


@pytest.mark.anyio
async def test_retriever_falls_back_through_strategies_and_caches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx.URL] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url)
        return httpx.Response(200, text="fallback evidence")

    _patch_async_client(monkeypatch, handler)

    retriever = LcscEvidenceRetriever(base_url="https://example.test")
    keys = SearchKeys(category="capacitator", footprint="0402", param_summary="1uF")

    first = await retriever.retrieve(keys)
    second = await retriever.retrieve(keys)

    assert [url for url in requests] == [
        httpx.URL("https://example.test/search?category=capacitator&footprint=0402&param_summary=1uF"),
    ]
    assert first == second
    assert len(first) == 1
    assert first[0].search_strategy == "parametric_fallback"
