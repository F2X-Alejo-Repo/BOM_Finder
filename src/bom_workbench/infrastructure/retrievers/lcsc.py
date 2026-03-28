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
logger = structlog.get_logger(__name__)


class LcscEvidenceRetriever(IEvidenceRetriever):
    """Fetch raw evidence from LCSC using deterministic lookup order."""

    def __init__(
        self,
        *,
        base_url: str = LCSC_BASE_URL,
        timeout_seconds: float = DEFAULT_READ_TIMEOUT,
    ) -> None:
        self._base_url = base_url.rstrip("/")
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

    def _strategies(self, keys: SearchKeys) -> list[tuple[str, dict[str, Any]]]:
        strategies: list[tuple[str, dict[str, Any]]] = []
        if keys.lcsc_part_number:
            strategies.append(
                (
                    "lcsc_product_detail",
                    {
                        "path": LCSC_PRODUCT_DETAIL_PATH.format(
                            part_number=keys.lcsc_part_number,
                        ),
                    },
                )
            )
            if keys.source_url:
                strategies.append(
                    (
                        "source_url",
                        {
                            "path": keys.source_url,
                        },
                    )
                )
            strategies.append(
                (
                    "lcsc_part_number",
                    {
                        "path": LCSC_SEARCH_PATH,
                        "params": {"searchTerm": keys.lcsc_part_number},
                    },
                )
            )
            return strategies
        if keys.mpn:
            strategies.append(
                (
                    "mpn",
                    {
                        "path": LCSC_SEARCH_PATH,
                        "params": {"searchTerm": keys.mpn},
                    },
                )
            )
            if keys.source_url:
                strategies.append(
                    (
                        "source_url",
                        {
                            "path": keys.source_url,
                        },
                    )
                )
            return strategies
        if keys.source_url:
            return [
                (
                    "source_url",
                    {
                        "path": keys.source_url,
                    },
                )
            ]

        params: dict[str, str] = {}
        if keys.category:
            params["category"] = keys.category
        if keys.footprint:
            params["footprint"] = keys.footprint
        if keys.param_summary:
            params["param_summary"] = keys.param_summary

        if not params:
            return []

        return [(
            "parametric_fallback",
            {
                "path": LCSC_SEARCH_PATH,
                "params": params,
            },
        )]

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

        if self._looks_like_generic_search_shell(content):
            return "", normalized_type or "text/html"
        return content, normalized_type or "text/html"

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
