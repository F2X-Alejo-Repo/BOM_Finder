"""Deterministic evidence retrieval for LCSC-backed part lookup."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import httpx
import structlog

from ...domain.ports import IEvidenceRetriever, RawEvidence
from ...domain.value_objects import SearchKeys
from ..providers.base import build_timeout

LCSC_BASE_URL = "https://www.lcsc.com"
LCSC_SEARCH_PATH = "/search"
LCSC_PRODUCT_DETAIL_PATH = "/product-detail/{part_number}.html"
LCSC_API_BASE_URL = "https://wmsc.lcsc.com"
LCSC_API_SEARCH_PATH = "/ftps/wbGetSearchMultiSearch"
LCSC_API_PAGE_SIZE = 25
DEFAULT_READ_TIMEOUT = 15.0
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}
LCSC_API_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.lcsc.com/",
    "Origin": "https://www.lcsc.com",
}
JLCPCB_API_BASE_URL = "https://cart.jlcpcb.com"
JLCPCB_COMPONENT_DETAIL_PATH = "/shoppingCart/smtGood/getComponentDetail"
JLCPCB_API_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://jlcpcb.com/",
    "Origin": "https://jlcpcb.com",
}
_OUT_OF_STOCK_STATUSES = {"out", "unavailable", "out_of_stock"}
logger = structlog.get_logger(__name__)


class LcscEvidenceRetriever(IEvidenceRetriever):
    """Fetch raw evidence from LCSC using deterministic lookup order."""

    def __init__(
        self,
        *,
        base_url: str = LCSC_BASE_URL,
        api_base_url: str = LCSC_API_BASE_URL,
        jlcpcb_api_base_url: str = JLCPCB_API_BASE_URL,
        timeout_seconds: float = DEFAULT_READ_TIMEOUT,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_base_url = api_base_url.rstrip("/") if api_base_url else ""
        self._jlcpcb_api_base_url = jlcpcb_api_base_url.rstrip("/") if jlcpcb_api_base_url else ""
        self._timeout_seconds = timeout_seconds
        self._cache: dict[str, list[RawEvidence]] = {}

    async def retrieve(self, search_keys: SearchKeys | Any) -> list[RawEvidence]:
        keys = search_keys if isinstance(search_keys, SearchKeys) else SearchKeys.model_validate(search_keys)
        cache_key = self._cache_key(keys)
        if cache_key in self._cache:
            logger.debug(
                "lcsc_retrieve_cache_hit",
                lcsc_part_number=keys.lcsc_part_number,
                mpn=keys.mpn,
            )
            return list(self._cache[cache_key])

        # Try the JSON API first — it returns structured data for any search term.
        api_evidence = await self._retrieve_via_api(keys)
        jlcpcb_evidence = await self._retrieve_jlcpcb_if_needed(keys, api_evidence)
        if api_evidence or jlcpcb_evidence:
            combined = list(api_evidence) + list(jlcpcb_evidence)
            self._cache[cache_key] = combined
            return combined

        # Fall back to HTML scraping (works for direct product-detail URLs / C-numbers).
        strategies = self._strategies(keys)
        if not strategies:
            self._cache[cache_key] = []
            return []

        async with httpx.AsyncClient(
            base_url=self._base_url,
            timeout=build_timeout(self._timeout_seconds),
            headers=DEFAULT_HEADERS,
            follow_redirects=True,
        ) as client:
            for strategy_name, request in strategies:
                logger.debug(
                    "lcsc_retrieve_attempt",
                    strategy=strategy_name,
                    path=request["path"],
                    params=request.get("params"),
                )
                try:
                    response = await client.get(request["path"], params=request.get("params"))
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    logger.warning(
                        "lcsc_retrieve_http_status_error",
                        strategy=strategy_name,
                        status_code=exc.response.status_code,
                        url=str(exc.request.url),
                    )
                    continue
                except httpx.RequestError as exc:
                    logger.warning(
                        "lcsc_retrieve_request_error",
                        strategy=strategy_name,
                        error_type=type(exc).__name__,
                        error=str(exc),
                    )
                    continue

                evidence = self._build_evidence(
                    response=response,
                    strategy_name=strategy_name,
                    source_url=str(response.url),
                    source_name="LCSC",
                )
                if evidence:
                    logger.debug(
                        "lcsc_retrieve_success",
                        strategy=strategy_name,
                        status_code=response.status_code,
                        url=str(response.url),
                        content_type=response.headers.get("content-type", ""),
                        content_bytes=len(response.text),
                    )
                    self._cache[cache_key] = evidence
                    return list(evidence)

        logger.info(
            "lcsc_retrieve_no_evidence",
            lcsc_part_number=keys.lcsc_part_number,
            mpn=keys.mpn,
            source_url=keys.source_url,
            category=keys.category,
            footprint=keys.footprint,
        )
        self._cache[cache_key] = []
        return []

    async def _retrieve_via_api(self, keys: SearchKeys) -> list[RawEvidence]:
        """Search LCSC's JSON API directly, trying multiple search terms."""
        search_terms: list[str] = []
        seen: set[str] = set()

        def _add(term: str) -> None:
            t = term.strip()
            if t and t not in seen:
                seen.add(t)
                search_terms.append(t)

        # Highest specificity first.
        _add(keys.lcsc_part_number)
        _add(keys.mpn)
        # Parametric / value fallback so footprint-only searches work.
        focused = str(keys.param_summary or keys.comment).strip()
        if focused:
            if keys.footprint:
                _add(f"{focused} {keys.footprint}")
            _add(focused)

        if not search_terms or not self._api_base_url:
            return []

        all_evidence: list[RawEvidence] = []
        async with httpx.AsyncClient(
            base_url=self._api_base_url,
            timeout=build_timeout(self._timeout_seconds),
            headers=LCSC_API_HEADERS,
            follow_redirects=True,
        ) as client:
            for term in search_terms:
                logger.debug("lcsc_api_search_attempt", keyword=term)
                try:
                    response = await client.get(
                        LCSC_API_SEARCH_PATH,
                        params={"keyword": term, "start": 0, "size": LCSC_API_PAGE_SIZE},
                    )
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    logger.warning(
                        "lcsc_api_search_http_error",
                        keyword=term,
                        status_code=exc.response.status_code,
                    )
                    continue
                except httpx.RequestError as exc:
                    logger.warning(
                        "lcsc_api_search_request_error",
                        keyword=term,
                        error_type=type(exc).__name__,
                        error=str(exc),
                    )
                    continue

                evidence = self._build_api_evidence(response, term)
                if evidence:
                    candidate_count = sum(
                        len(json.loads(ev.raw_content).get("candidates", []))
                        for ev in evidence
                        if ev.content_type == "application/json"
                    )
                    logger.debug(
                        "lcsc_api_search_success",
                        keyword=term,
                        candidate_count=candidate_count,
                    )
                    all_evidence.extend(evidence)
                    # Stop on the first term that returns results.
                    break

        return all_evidence

    async def _retrieve_jlcpcb_if_needed(
        self,
        keys: SearchKeys,
        lcsc_evidence: list[RawEvidence],
    ) -> list[RawEvidence]:
        """Query JLCPCB for C-numbers that are out of stock on LCSC, or if C-number is known."""
        if not self._jlcpcb_api_base_url:
            return []

        c_numbers: list[str] = []
        seen: set[str] = set()

        def _add_c(c: str) -> None:
            c = c.strip()
            if c and c not in seen:
                seen.add(c)
                c_numbers.append(c)

        # Always query JLCPCB when we have a known C-number (LCSC/JLCPCB share the namespace).
        if keys.lcsc_part_number:
            _add_c(keys.lcsc_part_number)

        # Also check LCSC results: if a part is out of stock there, try JLCPCB.
        for ev in lcsc_evidence:
            if ev.content_type != "application/json":
                continue
            try:
                data = json.loads(ev.raw_content)
            except Exception:
                continue
            for candidate in data.get("candidates", []):
                c_num = self._clean_text(candidate.get("lcsc_part_number") or "")
                stock_status = self._clean_text(candidate.get("stock_status") or "")
                stock_qty = candidate.get("stock_qty")
                is_out = stock_status in _OUT_OF_STOCK_STATUSES or (
                    isinstance(stock_qty, int) and stock_qty <= 0
                )
                if c_num and is_out:
                    _add_c(c_num)
            # Single-product evidence (not candidates list).
            c_num = self._clean_text(data.get("lcsc_part_number") or "")
            stock_status = self._clean_text(data.get("stock_status") or "")
            stock_qty = data.get("stock_qty")
            is_out = stock_status in _OUT_OF_STOCK_STATUSES or (
                isinstance(stock_qty, int) and stock_qty <= 0
            )
            if c_num and is_out:
                _add_c(c_num)

        if not c_numbers:
            return []

        return await self._retrieve_from_jlcpcb(c_numbers)

    async def _retrieve_from_jlcpcb(self, c_numbers: list[str]) -> list[RawEvidence]:
        """Fetch component details from JLCPCB for each C-number."""
        evidence: list[RawEvidence] = []
        async with httpx.AsyncClient(
            base_url=self._jlcpcb_api_base_url,
            timeout=build_timeout(self._timeout_seconds),
            headers=JLCPCB_API_HEADERS,
            follow_redirects=True,
        ) as client:
            for c_number in c_numbers:
                logger.debug("jlcpcb_retrieve_attempt", c_number=c_number)
                try:
                    response = await client.get(
                        JLCPCB_COMPONENT_DETAIL_PATH,
                        params={"componentCode": c_number},
                    )
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    logger.warning(
                        "jlcpcb_retrieve_http_error",
                        c_number=c_number,
                        status_code=exc.response.status_code,
                    )
                    continue
                except httpx.RequestError as exc:
                    logger.warning(
                        "jlcpcb_retrieve_request_error",
                        c_number=c_number,
                        error_type=type(exc).__name__,
                        error=str(exc),
                    )
                    continue

                ev = self._build_jlcpcb_evidence(response, c_number)
                if ev:
                    logger.debug(
                        "jlcpcb_retrieve_success",
                        c_number=c_number,
                        status_code=response.status_code,
                    )
                    evidence.extend(ev)
        return evidence

    def _build_jlcpcb_evidence(
        self, response: httpx.Response, c_number: str
    ) -> list[RawEvidence]:
        """Parse a JLCPCB component detail API response into RawEvidence."""
        try:
            data = response.json()
        except Exception:
            return []

        # JLCPCB wraps the component; try several known nesting structures.
        component: dict[str, Any] | None = None
        if isinstance(data, dict):
            inner = data.get("data") or data.get("result") or data
            if isinstance(inner, dict):
                # Some endpoints nest further under smtGoodVo or componentVO.
                nested = (
                    inner.get("smtGoodVo")
                    or inner.get("componentVO")
                    or inner.get("component")
                    or inner.get("smtGood")
                )
                component = nested if isinstance(nested, dict) else inner
        logger.debug(
            "jlcpcb_raw_response",
            c_number=c_number,
            component_keys=list(component.keys()) if component else [],
        )

        if not component:
            return []

        normalized = self._normalize_jlcpcb_product(component, c_number)
        if not normalized:
            return []
        if not normalized.get("mpn") or not normalized.get("manufacturer"):
            logger.debug(
                "jlcpcb_partial_fields",
                c_number=c_number,
                has_mpn=bool(normalized.get("mpn")),
                has_manufacturer=bool(normalized.get("manufacturer")),
                component_keys=list(component.keys()),
                component_sample={k: v for k, v in list(component.items())[:20]},
            )

        raw_content = json.dumps(
            normalized,
            ensure_ascii=True,
            separators=(",", ":"),
        )
        return [
            RawEvidence(
                source_url=f"https://jlcpcb.com/partdetail/{c_number}",
                source_name="JLCPCB",
                retrieved_at=datetime.now(UTC),
                content_type="application/json",
                raw_content=raw_content,
                search_strategy="jlcpcb_component_detail",
            )
        ]

    def _normalize_jlcpcb_product(
        self, component: dict[str, Any], c_number: str
    ) -> dict[str, Any] | None:
        """Map JLCPCB API fields to internal candidate field names."""
        lcsc_part_number = self._clean_text(
            component.get("componentCode") or component.get("lcscCode") or c_number
        )
        mpn = self._clean_text(
            component.get("componentModelEn")
            or component.get("componentModel")
            or component.get("erpProductName")
            or component.get("componentName")
            or component.get("mpn")
            or component.get("model")
            or ""
        )
        if not lcsc_part_number and not mpn:
            return None

        manufacturer = self._clean_text(
            component.get("componentBrandEn")
            or component.get("brandNameEn")
            or component.get("componentBrand")
            or component.get("brandName")
            or component.get("manufacturer")
            or component.get("brand")
            or ""
        )
        package = self._clean_text(
            component.get("componentSpecificationEn")
            or component.get("componentPackageEn")
            or component.get("encapStandard")
            or component.get("package")
            or component.get("footprint")
            or ""
        )
        description = self._clean_text(
            component.get("describe")
            or component.get("componentDescEn")
            or component.get("productDescEn")
            or component.get("description")
            or ""
        )
        stock_qty = self._coerce_int(
            self._first_not_none(component.get("stockCount"), component.get("stock"), component.get("stockNumber"))
        )
        overseas_stock = self._coerce_int(component.get("overseasStockCount"))
        moq = self._coerce_int(
            component.get("leastNumber")
            or component.get("minBuyNumber")
            or component.get("minOrder")
            or component.get("moq")
        )
        category = self._clean_text(
            component.get("catalogName")
            or component.get("componentTypeEn")
            or component.get("category")
            or ""
        )

        normalized: dict[str, Any] = {
            "source_name": "JLCPCB",
        }
        if lcsc_part_number:
            normalized["lcsc_part_number"] = lcsc_part_number
            normalized["lcsc_link"] = f"https://www.lcsc.com/product-detail/{lcsc_part_number}.html"
            normalized["jlcpcb_link"] = f"https://jlcpcb.com/partdetail/{lcsc_part_number}"
            normalized["source_url"] = normalized["jlcpcb_link"]
        if mpn:
            normalized["mpn"] = mpn
            normalized["part_number"] = mpn
        if manufacturer:
            normalized["manufacturer"] = manufacturer
        if package:
            normalized["package"] = package
            normalized["footprint"] = package
        if description:
            normalized["description"] = description
            normalized["param_summary"] = description
        if stock_qty is not None:
            normalized["stock_qty"] = stock_qty
            normalized["stock_status"] = self._infer_stock_status_from_quantity(stock_qty)
        if overseas_stock is not None:
            normalized["overseas_stock_qty"] = overseas_stock
        if moq is not None:
            normalized["moq"] = moq
        if category:
            normalized["category"] = category

        # Price tiers — JLCPCB uses various field names.
        price_list = (
            component.get("productPriceList")
            or component.get("priceList")
            or component.get("prices")
            or []
        )
        if isinstance(price_list, list) and price_list:
            tiers = []
            for entry in price_list:
                if not isinstance(entry, dict):
                    continue
                qty = self._coerce_int(entry.get("startNumber") or entry.get("ladder") or entry.get("quantity"))
                price = self._coerce_float(entry.get("productPrice") or entry.get("usdPrice") or entry.get("price"))
                if qty is not None and price is not None:
                    tiers.append({"quantity": qty, "unit_price_usd": price, "currency": "USD"})
            if tiers:
                normalized["price_tiers"] = tiers
                normalized["unit_price_usd"] = tiers[0]["unit_price_usd"]
                normalized["price_currency"] = "USD"

        return normalized or None

    def _build_api_evidence(self, response: httpx.Response, search_term: str) -> list[RawEvidence]:
        """Parse an LCSC JSON API response into RawEvidence items."""
        try:
            data = response.json()
        except Exception:
            return []

        # The LCSC API wraps results: {"code": 200, "result": {"productList": [...], "totalCount": N}}
        product_list: list[Any] = []
        if isinstance(data, list):
            product_list = data
        elif isinstance(data, dict):
            result = data.get("result") or data.get("data") or data
            if isinstance(result, list):
                product_list = result
            elif isinstance(result, dict):
                for key in ("productList", "products", "list", "items"):
                    value = result.get(key)
                    if isinstance(value, list):
                        product_list = value
                        break
                if not product_list:
                    # Treat result itself as a single product dict.
                    product_list = [result]

        if not product_list:
            logger.debug("lcsc_api_search_empty_result", keyword=search_term)
            return []

        candidates = [
            normalized
            for product in product_list
            if isinstance(product, dict)
            for normalized in [self._normalize_api_product(product, search_term=search_term)]
            if normalized
        ]
        if not candidates:
            return []

        raw_content = json.dumps(
            {"candidates": candidates},
            ensure_ascii=True,
            separators=(",", ":"),
        )
        return [
            RawEvidence(
                source_url=str(response.url),
                source_name="LCSC",
                retrieved_at=datetime.now(UTC),
                content_type="application/json",
                raw_content=raw_content,
                search_strategy="lcsc_api_search",
            )
        ]

    def _normalize_api_product(
        self,
        product: dict[str, Any],
        *,
        search_term: str = "",
    ) -> dict[str, Any] | None:
        """Convert LCSC API product fields to the internal candidate field names."""
        lcsc_part_number = self._clean_text(
            product.get("productCode") or product.get("lcscCode") or product.get("sku") or ""
        )
        mpn = self._clean_text(
            product.get("productModel") or product.get("mpn") or product.get("model") or ""
        )
        if not lcsc_part_number and not mpn:
            return None

        manufacturer = self._clean_text(
            product.get("brandNameEn") or product.get("brandName") or product.get("manufacturer") or ""
        )
        package = self._clean_text(
            product.get("encapStandard") or product.get("package") or product.get("footprint") or ""
        )
        description = self._clean_text(
            product.get("productDescEn")
            or product.get("productDesc")
            or product.get("description")
            or product.get("title")
            or ""
        )
        stock_qty = self._coerce_int(
            self._first_not_none(product.get("stockNumber"), product.get("stockCount"), product.get("stock"))
        )
        product_cycle = self._clean_text(
            product.get("productCycle") or product.get("lifecycle") or ""
        )
        lifecycle_status = self._normalize_product_cycle(product_cycle)
        catalog = self._clean_text(product.get("catalogName") or product.get("category") or "")
        parent_catalog = self._clean_text(product.get("parentCatalogName") or "")
        category = f"{parent_catalog}/{catalog}" if parent_catalog and catalog else catalog

        normalized: dict[str, Any] = {}
        if lcsc_part_number:
            normalized["lcsc_part_number"] = lcsc_part_number
            normalized["lcsc_link"] = f"https://www.lcsc.com/product-detail/{lcsc_part_number}.html"
            normalized["source_url"] = normalized["lcsc_link"]
        if mpn:
            normalized["mpn"] = mpn
            normalized["part_number"] = mpn
        if manufacturer:
            normalized["manufacturer"] = manufacturer
        if package:
            normalized["package"] = package
            normalized["footprint"] = package
        if description:
            normalized["description"] = description
            normalized["param_summary"] = description
            normalized["value_summary"] = description
        if stock_qty is not None:
            normalized["stock_qty"] = stock_qty
            normalized["stock_status"] = self._infer_stock_status_from_quantity(stock_qty)
        if lifecycle_status:
            normalized["lifecycle_status"] = lifecycle_status
        if category:
            normalized["category"] = category

        # Price tiers — accept multiple field names.
        price_list = (
            product.get("productPriceList")
            or product.get("priceList")
            or product.get("prices")
            or []
        )
        if isinstance(price_list, list) and price_list:
            first = price_list[0]
            if isinstance(first, dict):
                price = self._coerce_float(
                    first.get("usdPrice") or first.get("price") or first.get("unitPrice")
                )
                if price is not None:
                    normalized["unit_price_usd"] = price
                    normalized["price_currency"] = "USD"

        return normalized or None

    def _strategies(self, keys: SearchKeys) -> list[tuple[str, dict[str, Any]]]:
        strategies: list[tuple[str, dict[str, Any]]] = []
        seen_requests: set[tuple[str, str]] = set()
        fallback_params = self._fallback_params(keys)

        def add_strategy(
            strategy_name: str,
            *,
            path: str,
            params: Mapping[str, Any] | None = None,
        ) -> None:
            normalized_params = {
                str(key): str(value)
                for key, value in (params or {}).items()
                if str(value).strip()
            }
            fingerprint = (
                path,
                json.dumps(normalized_params, ensure_ascii=True, sort_keys=True),
            )
            if fingerprint in seen_requests:
                return
            seen_requests.add(fingerprint)
            request: dict[str, Any] = {"path": path}
            if normalized_params:
                request["params"] = normalized_params
            strategies.append((strategy_name, request))

        if keys.lcsc_part_number:
            add_strategy(
                "lcsc_product_detail",
                path=LCSC_PRODUCT_DETAIL_PATH.format(
                    part_number=keys.lcsc_part_number,
                ),
            )
            if keys.source_url:
                add_strategy("source_url", path=keys.source_url)
            add_strategy(
                "lcsc_part_number",
                path=LCSC_SEARCH_PATH,
                params={"searchTerm": keys.lcsc_part_number},
            )
            if keys.mpn:
                add_strategy(
                    "mpn",
                    path=LCSC_SEARCH_PATH,
                    params={"searchTerm": keys.mpn},
                )
            self._append_search_fallback_strategies(
                strategies,
                add_strategy,
                keys,
                fallback_params=fallback_params,
            )
            return strategies
        if keys.mpn:
            add_strategy(
                "mpn",
                path=LCSC_SEARCH_PATH,
                params={"searchTerm": keys.mpn},
            )
            if keys.source_url:
                add_strategy("source_url", path=keys.source_url)
            self._append_search_fallback_strategies(
                strategies,
                add_strategy,
                keys,
                fallback_params=fallback_params,
            )
            return strategies
        if keys.source_url:
            add_strategy("source_url", path=keys.source_url)
            self._append_search_fallback_strategies(
                strategies,
                add_strategy,
                keys,
                fallback_params=fallback_params,
            )
            return strategies

        self._append_search_fallback_strategies(
            strategies,
            add_strategy,
            keys,
            fallback_params=fallback_params,
        )
        return strategies

    def _append_search_fallback_strategies(
        self,
        strategies: list[tuple[str, dict[str, Any]]],
        add_strategy: Any,
        keys: SearchKeys,
        *,
        fallback_params: Mapping[str, Any],
    ) -> None:
        del strategies
        if fallback_params:
            add_strategy(
                "parametric_fallback",
                path=LCSC_SEARCH_PATH,
                params=fallback_params,
            )

        value_footprint_term = self._value_footprint_search_term(keys)
        if value_footprint_term:
            add_strategy(
                "value_footprint_search",
                path=LCSC_SEARCH_PATH,
                params={"searchTerm": value_footprint_term},
            )

        for strategy_name, value in (
            ("comment_search", keys.comment),
            ("param_summary_search", keys.param_summary),
        ):
            term = str(value).strip()
            if not term:
                continue
            add_strategy(
                strategy_name,
                path=LCSC_SEARCH_PATH,
                params={"searchTerm": term},
            )

    def _fallback_params(self, keys: SearchKeys) -> dict[str, str]:
        params: dict[str, str] = {}
        if keys.category:
            params["category"] = keys.category
        if keys.footprint:
            params["footprint"] = keys.footprint
        if keys.param_summary:
            params["param_summary"] = keys.param_summary
        elif keys.comment:
            params["param_summary"] = keys.comment
        return params

    def _value_footprint_search_term(self, keys: SearchKeys) -> str:
        summary = str(keys.param_summary or keys.comment).strip()
        footprint = str(keys.footprint).strip()
        if not summary or not footprint:
            return ""
        return f"{summary} {footprint}"

    def _build_evidence(
        self,
        *,
        response: httpx.Response,
        strategy_name: str,
        source_url: str,
        source_name: str,
    ) -> list[RawEvidence]:
        content = response.text.strip()
        if not content:
            return []

        normalized_source_name = self._source_name_for_url(source_url, default=source_name)
        normalized_content, normalized_content_type = self._normalize_response_content(
            content=content,
            content_type=response.headers.get("content-type", "text/plain"),
            source_url=source_url,
            source_name=normalized_source_name,
        )
        if not normalized_content:
            logger.debug(
                "lcsc_retrieve_skipped_unusable_response",
                strategy=strategy_name,
                source_url=source_url,
                source_name=normalized_source_name,
            )
            return []

        retrieved_at = datetime.now(UTC)
        return [
            RawEvidence(
                source_url=source_url,
                source_name=normalized_source_name,
                retrieved_at=retrieved_at,
                content_type=normalized_content_type,
                raw_content=normalized_content,
                search_strategy=strategy_name,
            )
        ]

    def _normalize_response_content(
        self,
        *,
        content: str,
        content_type: str,
        source_url: str,
        source_name: str,
    ) -> tuple[str, str]:
        normalized_type = content_type.split(";")[0].strip().lower()
        if "html" not in normalized_type:
            return content, normalized_type or "text/plain"

        structured_payload = self._extract_product_payload_from_html(
            content,
            source_url=source_url,
            source_name=source_name,
        )
        if structured_payload is not None:
            return (
                json.dumps(
                    structured_payload,
                    ensure_ascii=True,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                "application/json",
            )
        return "", normalized_type or "text/html"

    def _extract_product_payload_from_html(
        self,
        html: str,
        *,
        source_url: str,
        source_name: str,
    ) -> dict[str, Any] | None:
        payload: dict[str, Any] = {
            "source_url": source_url,
            "source_name": source_name,
        }
        json_ld_payload = self._extract_product_payload_from_json_ld(
            html,
            source_url=source_url,
            source_name=source_name,
        )
        nuxt_payload = self._extract_product_payload_from_nuxt(
            html,
            source_url=source_url,
            source_name=source_name,
        )
        if json_ld_payload:
            payload.update(json_ld_payload)
        if nuxt_payload:
            payload.update(
                {
                    key: value
                    for key, value in nuxt_payload.items()
                    if not self._is_empty_payload_value(value)
                }
            )
        if len(payload) <= 2:
            return None
        if "stock_status" not in payload:
            stock_status = self._stock_status_from_title(html)
            if stock_status:
                payload["stock_status"] = stock_status
        return payload

    def _extract_product_payload_from_json_ld(
        self,
        html: str,
        *,
        source_url: str,
        source_name: str,
    ) -> dict[str, Any] | None:
        for candidate in self._extract_json_ld_objects(html):
            product_type = str(candidate.get("@type", "")).strip().casefold()
            if product_type != "product":
                continue

            payload: dict[str, Any] = {
                "source_url": source_url,
                "source_name": source_name,
            }
            name = str(candidate.get("name", "")).strip()
            brand = candidate.get("brand")
            manufacturer = ""
            if isinstance(brand, Mapping):
                manufacturer = str(brand.get("name", "")).strip()
            elif brand is not None:
                manufacturer = str(brand).strip()
            mpn = str(candidate.get("mpn", "")).strip()
            sku = str(candidate.get("sku", "")).strip()
            description = str(candidate.get("description", "")).strip()
            category = str(candidate.get("category", "")).strip()
            offers = candidate.get("offers")
            availability = ""
            if isinstance(offers, Mapping):
                availability = str(offers.get("availability", "")).strip()
                offer_url = str(offers.get("url", "")).strip()
                if offer_url:
                    payload["source_url"] = offer_url
                inventory_level = self._coerce_int(offers.get("inventoryLevel"))
                if inventory_level is not None:
                    payload["stock_qty"] = inventory_level
                unit_price = self._coerce_float(offers.get("price"))
                if unit_price is not None:
                    payload["unit_price_usd"] = unit_price
                price_currency = str(offers.get("priceCurrency", "")).strip()
                if price_currency:
                    payload["price_currency"] = price_currency

            if name:
                payload["product_name"] = name
            if manufacturer:
                payload["manufacturer"] = manufacturer
            if mpn:
                payload["mpn"] = mpn
            if sku:
                payload["lcsc_part_number"] = sku
            if category:
                payload["category"] = category
            if description:
                payload["description"] = description
                payload["param_summary"] = description
                package = self._extract_package_from_text(description)
                if package:
                    payload["package"] = package
            stock_status = self._stock_status_from_availability(availability) or self._stock_status_from_title(html)
            if stock_status:
                payload["stock_status"] = stock_status
            return payload
        return None

    def _extract_product_payload_from_nuxt(
        self,
        html: str,
        *,
        source_url: str,
        source_name: str,
    ) -> dict[str, Any] | None:
        expression = self._extract_nuxt_expression(html)
        if not expression:
            return None
        variables = self._parse_nuxt_variables(expression)
        detail_block = self._extract_nuxt_detail_block(expression)
        if not detail_block:
            return None

        payload: dict[str, Any] = {
            "source_url": source_url,
            "source_name": source_name,
        }
        lcsc_part_number = self._clean_text(
            self._extract_nuxt_scalar(detail_block, "productCode", variables)
        )
        mpn = self._clean_text(self._extract_nuxt_scalar(detail_block, "productModel", variables))
        manufacturer = self._clean_text(
            self._extract_nuxt_scalar(detail_block, "brandNameEn", variables)
        )
        package = self._clean_text(
            self._extract_nuxt_scalar(detail_block, "encapStandard", variables)
        )
        parent_catalog = self._clean_text(
            self._extract_nuxt_scalar(detail_block, "parentCatalogName", variables)
        )
        catalog = self._clean_text(self._extract_nuxt_scalar(detail_block, "catalogName", variables))
        description = self._clean_text(
            self._extract_nuxt_scalar(detail_block, "productDescEn", variables)
            or self._extract_nuxt_scalar(detail_block, "productIntroEn", variables)
        )
        product_name = self._clean_text(
            self._extract_nuxt_scalar(detail_block, "title", variables)
            or self._extract_nuxt_scalar(detail_block, "productNameEn", variables)
        )
        stock_qty = self._coerce_int(
            self._extract_nuxt_scalar(detail_block, "stockNumber", variables)
            or self._extract_nuxt_scalar(detail_block, "stockSz", variables)
        )
        moq = self._coerce_int(self._extract_nuxt_scalar(detail_block, "minBuyNumber", variables))
        order_multiple = self._coerce_int(self._extract_nuxt_scalar(detail_block, "split", variables))
        standard_pack_quantity = self._coerce_int(
            self._extract_nuxt_scalar(detail_block, "minPacketNumber", variables)
        )
        product_cycle = self._clean_text(
            self._extract_nuxt_scalar(detail_block, "productCycle", variables)
        )
        packaging = self._clean_text(
            self._extract_nuxt_scalar(detail_block, "productArrange", variables)
        )
        datasheet_url = self._clean_text(self._extract_nuxt_scalar(detail_block, "pdfUrl", variables))
        if datasheet_url.startswith("/"):
            datasheet_url = f"{self._base_url}{datasheet_url}"
        lifecycle_status = self._normalize_product_cycle(product_cycle)
        if lcsc_part_number:
            payload["lcsc_part_number"] = lcsc_part_number
        if mpn:
            payload["mpn"] = mpn
        if manufacturer:
            payload["manufacturer"] = manufacturer
        if package:
            payload["package"] = package
        if parent_catalog and catalog:
            payload["category"] = f"{parent_catalog}/{catalog}"
        elif catalog:
            payload["category"] = catalog
        if description:
            payload["description"] = description
            payload["param_summary"] = description
        if product_name:
            payload["product_name"] = product_name
        if stock_qty is not None:
            payload["stock_qty"] = stock_qty
            payload["stock_status"] = self._infer_stock_status_from_quantity(stock_qty)
        if moq is not None:
            payload["moq"] = moq
        if order_multiple is not None:
            payload["order_multiple"] = order_multiple
        if standard_pack_quantity is not None:
            payload["standard_pack_quantity"] = standard_pack_quantity
        if product_cycle:
            payload["product_cycle"] = product_cycle
        if lifecycle_status:
            payload["lifecycle_status"] = lifecycle_status
        if packaging:
            payload["packaging"] = packaging
        if datasheet_url:
            payload["datasheet_url"] = datasheet_url
        price_tiers = self._extract_nuxt_price_tiers(detail_block, variables)
        if price_tiers:
            payload["price_tiers"] = price_tiers
            lowest_tier = min(
                (
                    tier
                    for tier in price_tiers
                    if isinstance(tier.get("unit_price_usd"), (int, float))
                ),
                key=lambda tier: float(tier["unit_price_usd"]),
                default=None,
            )
            if lowest_tier is not None:
                payload["unit_price_usd"] = float(lowest_tier["unit_price_usd"])
                payload["price_currency"] = self._clean_text(lowest_tier.get("currency", "")) or "USD"
        return payload

    def _extract_json_ld_objects(self, html: str) -> list[dict[str, Any]]:
        matches = re.findall(
            r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
            html,
            re.IGNORECASE | re.DOTALL,
        )
        objects: list[dict[str, Any]] = []
        for match in matches:
            text = match.strip()
            if not text:
                continue
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                objects.append(parsed)
            elif isinstance(parsed, list):
                objects.extend(item for item in parsed if isinstance(item, dict))
        return objects

    def _extract_nuxt_expression(self, html: str) -> str:
        marker = "window.__NUXT__="
        start = html.find(marker)
        if start < 0:
            return ""
        end = html.find("</script>", start)
        if end < 0:
            return ""
        return html[start + len(marker) : end].strip()

    def _parse_nuxt_variables(self, expression: str) -> dict[str, Any]:
        match = re.match(
            r"^\(function\((?P<params>.*?)\)\{\s*return\s+",
            expression,
            re.DOTALL,
        )
        invocation_start = expression.rfind("}(")
        separator_length = 2
        if invocation_start < 0:
            invocation_start = expression.rfind("})(")
            separator_length = 3
        invocation_end = expression.rfind(")")
        if match is None:
            return {}
        if invocation_start < 0 or invocation_end <= invocation_start:
            return {}

        params = [
            item.strip()
            for item in match.group("params").split(",")
            if item.strip()
        ]
        args = self._parse_nuxt_argument_list(
            expression[invocation_start + separator_length : invocation_end]
        )
        return {
            key: value
            for key, value in zip(params, args, strict=False)
        }

    def _parse_nuxt_argument_list(self, text: str) -> list[Any]:
        values: list[Any] = []
        current: list[str] = []
        in_string = False
        escaped = False
        for char in text:
            if in_string:
                current.append(char)
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                current.append(char)
                in_string = True
                continue
            if char == ",":
                token = "".join(current).strip()
                if token:
                    values.append(self._parse_nuxt_literal(token))
                current = []
                continue
            current.append(char)
        token = "".join(current).strip()
        if token:
            values.append(self._parse_nuxt_literal(token))
        return values

    def _parse_nuxt_literal(self, token: str) -> Any:
        text = token.strip()
        if text == "null":
            return None
        if text == "true":
            return True
        if text == "false":
            return False
        if text.startswith('"') and text.endswith('"'):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return text.strip('"')
        if re.fullmatch(r"-?\d+", text):
            return int(text)
        if re.fullmatch(r"-?(?:\d+\.\d+|\.\d+)", text):
            return float(text)
        return text

    def _extract_nuxt_detail_block(self, expression: str) -> str:
        match = re.search(r"\bdetail\s*:\s*\{", expression)
        if match is None:
            return ""
        brace_start = match.end() - 1
        return self._extract_balanced_segment(expression, brace_start, "{", "}")

    def _extract_balanced_segment(
        self,
        text: str,
        start_index: int,
        open_char: str,
        close_char: str,
    ) -> str:
        if start_index < 0 or start_index >= len(text) or text[start_index] != open_char:
            return ""
        depth = 0
        in_string = False
        escaped = False
        for index in range(start_index, len(text)):
            char = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
                continue
            if char == open_char:
                depth += 1
                continue
            if char == close_char:
                depth -= 1
                if depth == 0:
                    return text[start_index : index + 1]
        return ""

    def _extract_nuxt_scalar(
        self,
        detail_block: str,
        field_name: str,
        variables: Mapping[str, Any],
    ) -> Any:
        pattern = re.compile(
            rf"{re.escape(field_name)}\s*:\s*(\"(?:\\.|[^\"])*\"|-?(?:\d+\.\d+|\.\d+|\d+)|null|true|false|[A-Za-z_$][A-Za-z0-9_$]*)"
        )
        match = pattern.search(detail_block)
        if not match:
            return None
        return self._resolve_nuxt_value(match.group(1), variables)

    def _resolve_nuxt_value(self, token: str, variables: Mapping[str, Any]) -> Any:
        text = token.strip()
        if text in variables:
            return variables[text]
        return self._parse_nuxt_literal(text)

    def _extract_nuxt_price_tiers(
        self,
        detail_block: str,
        variables: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        match = re.search(r"\bproductPriceList\s*:\s*\[", detail_block)
        if match is None:
            return []
        list_block = self._extract_balanced_segment(
            detail_block,
            match.end() - 1,
            "[",
            "]",
        )
        if not list_block:
            return []
        tiers: list[dict[str, Any]] = []
        for entry in re.findall(r"\{(.*?)\}", list_block, re.DOTALL):
            ladder = self._extract_nuxt_scalar(entry, "ladder", variables)
            unit_price = self._extract_nuxt_scalar(entry, "usdPrice", variables)
            currency = self._extract_nuxt_scalar(entry, "currencySymbol", variables)
            ext_price = self._extract_nuxt_scalar(entry, "extPrice", variables)
            tier: dict[str, Any] = {}
            ladder_value = self._coerce_int(ladder)
            unit_price_value = self._coerce_float(unit_price)
            ext_price_value = self._coerce_float(ext_price)
            currency_value = self._normalize_currency(currency)
            if ladder_value is not None:
                tier["quantity"] = ladder_value
            if unit_price_value is not None:
                tier["unit_price_usd"] = unit_price_value
            if ext_price_value is not None:
                tier["extended_price_usd"] = ext_price_value
            if currency_value:
                tier["currency"] = currency_value
            if tier:
                tiers.append(tier)
        return tiers

    def _normalize_product_cycle(self, value: str) -> str:
        normalized = value.strip().casefold().replace(" ", "_").replace("-", "_")
        mapping = {
            "normal": "active",
            "active": "active",
            "in_production": "active",
            "production": "active",
            "nrnd": "nrnd",
            "not_recommended_for_new_designs": "nrnd",
            "ltb": "last_time_buy",
            "last_time_buy": "last_time_buy",
            "eol": "eol",
            "obsolete": "eol",
        }
        return mapping.get(normalized, "")

    def _infer_stock_status_from_quantity(self, stock_qty: int) -> str:
        if stock_qty <= 0:
            return "out"
        if stock_qty <= 10:
            return "low"
        if stock_qty <= 100:
            return "medium"
        return "high"

    @staticmethod
    def _first_not_none(*values: Any) -> Any:
        for v in values:
            if v is not None:
                return v
        return None

    def _coerce_int(self, value: Any) -> int | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if value is None:
            return None
        text = str(value).strip().replace(",", "")
        match = re.search(r"-?\d+", text)
        if not match:
            return None
        return int(match.group(0))

    def _coerce_float(self, value: Any) -> float | None:
        if isinstance(value, bool) or value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).strip().replace(",", "")
        match = re.search(r"-?(?:\d+\.\d+|\.\d+|\d+)", text)
        if not match:
            return None
        return float(match.group(0))

    def _is_empty_payload_value(self, value: Any) -> bool:
        return value in (None, "", [], {})

    def _clean_text(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        return str(value).strip()

    def _normalize_currency(self, value: Any) -> str:
        text = self._clean_text(value).upper()
        mapping = {
            "$": "USD",
            "US$": "USD",
        }
        return mapping.get(text, text)

    def _stock_status_from_availability(self, value: str) -> str:
        normalized = value.strip().casefold()
        if not normalized:
            return ""
        if "instock" in normalized or "in_stock" in normalized:
            return "high"
        if "outofstock" in normalized or "out_of_stock" in normalized:
            return "out"
        return ""

    def _stock_status_from_title(self, html: str) -> str:
        title_match = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        if not title_match:
            return ""
        title = title_match.group(1)
        if re.search(r"\bin stock\b", title, re.IGNORECASE):
            return "high"
        if re.search(r"\bout of stock\b", title, re.IGNORECASE):
            return "out"
        return ""

    def _extract_package_from_text(self, value: str) -> str:
        match = re.search(r"\b(0201|0402|0603|0805|1206|1210|1812|2220)\b", value)
        return match.group(1) if match else ""

    def _looks_like_generic_search_shell(self, html: str) -> bool:
        if not re.search(r"<html", html, re.IGNORECASE):
            return False
        generic_title = "LCSC Electronics - Electronic Components Distributor"
        if generic_title.casefold() in html.casefold():
            return True
        if "routePath:\\\"/search\\\"" in html or 'routePath:"/search"' in html:
            return True
        return False

    def _source_name_for_url(self, url: str, *, default: str) -> str:
        host = urlparse(url).netloc.casefold()
        if "jlcpcb.com" in host:
            return "JLCPCB"
        if "lcsc.com" in host:
            return "LCSC"
        return default

    def _cache_key(self, keys: SearchKeys) -> str:
        payload = "|".join(
            [
                keys.lcsc_part_number,
                keys.mpn,
                keys.source_url,
                keys.comment,
                keys.footprint,
                keys.category,
                keys.param_summary,
            ]
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
