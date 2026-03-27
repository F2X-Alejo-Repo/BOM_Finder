"""Deterministic evidence retrieval for LCSC-backed part lookup."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import httpx
import structlog

from ...domain.ports import IEvidenceRetriever, RawEvidence
from ...domain.value_objects import SearchKeys
from ..providers.base import build_timeout

LCSC_BASE_URL = "https://www.lcsc.com"
LCSC_SEARCH_PATH = "/search"
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
        if keys.lcsc_part_number:
            return [(
                "lcsc_part_number",
                {
                    "path": LCSC_SEARCH_PATH,
                    "params": {"searchTerm": keys.lcsc_part_number},
                },
            )]
        if keys.mpn:
            return [(
                "mpn",
                {
                    "path": LCSC_SEARCH_PATH,
                    "params": {"searchTerm": keys.mpn},
                },
            )]
        if keys.source_url:
            return [(
                "source_url",
                {
                    "path": keys.source_url,
                },
            )]

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

        retrieved_at = datetime.now(UTC)
        content_type = response.headers.get("content-type", "text/plain").split(";")[0].strip()
        return [
            RawEvidence(
                source_url=source_url,
                source_name=source_name,
                retrieved_at=retrieved_at,
                content_type=content_type,
                raw_content=content,
                search_strategy=strategy_name,
            )
        ]

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
