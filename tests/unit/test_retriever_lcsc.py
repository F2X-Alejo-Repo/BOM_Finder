from __future__ import annotations

import json

import httpx
import pytest

from bom_workbench.domain.value_objects import SearchKeys
from bom_workbench.infrastructure.retrievers import LcscEvidenceRetriever

_C14663_PRODUCT_HTML = """<!doctype html>
<html lang="en-US">
  <head>
    <title>CC0603KRX7R9BB104 | YAGEO | Price | In Stock | LCSC Electronics</title>
    <meta name="description" content="CC0603KRX7R9BB104 by YAGEO - In-stock components at LCSC.">
    <script type="application/ld+json">
      {
        "@context": "http://schema.org",
        "@type": "Product",
        "name": "YAGEO CC0603KRX7R9BB104",
        "sku": "C14663",
        "mpn": "CC0603KRX7R9BB104",
        "brand": "YAGEO",
        "description": "100nF +-10% 50V Ceramic Capacitor X7R 0603",
        "category": "Capacitors/Ceramic Capacitors",
        "offers": {
          "@type": "Offer",
          "url": "https://www.lcsc.com/product-detail/C14663.html",
          "priceCurrency": "USD",
          "price": "0.0015",
          "inventoryLevel": 2314200,
          "availability": "https://schema.org/InStock"
        }
      }
    </script>
    <script>
      window.__NUXT__=(function(a,b,c,d,e,f,g,h,i,j,k,l,m,n,o,p){
        return {
          data: [{
            detail: {
              productCode: "C14663",
              productModel: "CC0603KRX7R9BB104",
              title: "YAGEO CC0603KRX7R9BB104",
              brandNameEn: "YAGEO",
              parentCatalogName: h,
              catalogName: i,
              encapStandard: "0603",
              split: j,
              minBuyNumber: j,
              maxBuyNumber: k,
              minPacketNumber: l,
              productDescEn: m,
              productIntroEn: m,
              productCycle: n,
              productArrange: o,
              stockNumber: e,
              stockSz: e,
              isPreSale: b,
              domesticStockVO: {total: e, shipImmediately: e, ship3Days: p},
              overseasStockVO: {total: e, shipImmediately: e, ship3Days: p},
              productPriceList: [
                {ladder: j, productPrice: "0.0028", usdPrice: f, currencySymbol: d, extPrice: "0.28"},
                {ladder: l, productPrice: "0.0018", usdPrice: g, currencySymbol: d, extPrice: "7.20"}
              ],
              pdfUrl: "/datasheet/C14663.pdf"
            }
          }]
        }
      })(null,false,true,"$",2314200,0.0028,0.0018,"Capacitors","Ceramic Capacitors",100,-1,4000,"100nF ±10% 50V Ceramic Capacitor X7R 0603","normal","Tape & Reel (TR)",0)
    </script>
  </head>
  <body></body>
</html>"""

_C14663_SEARCH_SHELL_HTML = """<!doctype html>
<html lang="en">
  <head>
    <title>LCSC Electronics - Electronic Components Distributor</title>
  </head>
  <body>
    <script>window.__NUXT__=function(e){return{layout:"v2Main",routePath:"/search",config:{}}}(null)</script>
  </body>
</html>"""


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
        return httpx.Response(
            200,
            text=_C14663_PRODUCT_HTML,
            headers={"content-type": "text/html; charset=utf-8"},
        )

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

    assert seen_urls == [httpx.URL("https://example.test/product-detail/C12345.html")]
    assert len(evidence) == 1
    assert evidence[0].search_strategy == "lcsc_product_detail"
    assert evidence[0].source_name == "LCSC"
    assert evidence[0].content_type == "application/json"
    payload = json.loads(evidence[0].raw_content)
    assert payload["mpn"] == "CC0603KRX7R9BB104"
    assert payload["manufacturer"] == "YAGEO"
    assert payload["lcsc_part_number"] == "C14663"
    assert payload["stock_status"] == "high"
    assert payload["stock_qty"] == 2314200
    assert payload["moq"] == 100
    assert payload["order_multiple"] == 100
    assert payload["standard_pack_quantity"] == 4000
    assert payload["lifecycle_status"] == "active"
    assert payload["packaging"] == "Tape & Reel (TR)"
    assert payload["datasheet_url"] == "https://example.test/datasheet/C14663.pdf"
    assert payload["price_currency"] == "USD"
    assert payload["unit_price_usd"] == pytest.approx(0.0018)
    assert payload["price_tiers"] == [
        {"quantity": 100, "unit_price_usd": pytest.approx(0.0028), "extended_price_usd": pytest.approx(0.28), "currency": "USD"},
        {"quantity": 4000, "unit_price_usd": pytest.approx(0.0018), "extended_price_usd": pytest.approx(7.2), "currency": "USD"},
    ]
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


@pytest.mark.anyio
async def test_retriever_skips_generic_search_shell_and_falls_back_to_source_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx.URL] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url)
        if request.url.path.endswith("/product-detail/C14663.html"):
            return httpx.Response(
                200,
                text=_C14663_SEARCH_SHELL_HTML,
                headers={"content-type": "text/html"},
            )
        if "jlcpcb.com" in request.url.host:
            return httpx.Response(
                200,
                text=_C14663_PRODUCT_HTML,
                headers={"content-type": "text/html; charset=utf-8"},
            )
        return httpx.Response(200, text=_C14663_SEARCH_SHELL_HTML, headers={"content-type": "text/html"})

    _patch_async_client(monkeypatch, handler)

    retriever = LcscEvidenceRetriever(base_url="https://www.lcsc.com")
    evidence = await retriever.retrieve(
        SearchKeys(
            lcsc_part_number="C14663",
            source_url="https://jlcpcb.com/partdetail/Yageo-CC0603KRX7R9BB104/C14663",
        )
    )

    assert requests[:2] == [
        httpx.URL("https://www.lcsc.com/product-detail/C14663.html"),
        httpx.URL("https://jlcpcb.com/partdetail/Yageo-CC0603KRX7R9BB104/C14663"),
    ]
    assert len(evidence) == 1
    assert evidence[0].search_strategy == "source_url"
    assert evidence[0].source_name == "JLCPCB"
    payload = json.loads(evidence[0].raw_content)
    assert payload["lcsc_part_number"] == "C14663"
    assert payload["source_name"] == "JLCPCB"
