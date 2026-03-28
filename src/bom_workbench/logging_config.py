"""Centralized console logging configuration for BOM Workbench."""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Mapping, MutableMapping
from typing import Any, Final

import structlog
from structlog.processors import CallsiteParameter

LOG_LEVEL_CHOICES: Final[tuple[str, ...]] = (
    "CRITICAL",
    "ERROR",
    "WARNING",
    "INFO",
    "DEBUG",
    "TRACE",
)
_NOISY_LOGGERS: Final[tuple[str, ...]] = (
    "asyncio",
    "httpx",
    "httpcore",
)
_SENSITIVE_FIELD_MARKERS: Final[tuple[str, ...]] = (
    "api_key",
    "apikey",
    "authorization",
    "password",
    "secret",
    "token",
    "bearer",
    "session_key",
    "access_key",
    "client_secret",
)
_REDACTED: Final[str] = "***REDACTED***"
TRACE_LEVEL = 5


def _install_trace_level() -> None:
    logging.addLevelName(TRACE_LEVEL, "TRACE")
    if hasattr(logging.Logger, "trace"):
        return

    def trace(self: logging.Logger, msg: str, *args: object, **kwargs: object) -> None:
        if self.isEnabledFor(TRACE_LEVEL):
            self._log(TRACE_LEVEL, msg, args, **kwargs)

    logging.Logger.trace = trace  # type: ignore[attr-defined]


def _resolve_log_level(log_level: str) -> tuple[str, int]:
    normalized_level = str(log_level).strip().upper()
    if normalized_level == "TRACE":
        return normalized_level, TRACE_LEVEL

    level = logging.getLevelNamesMapping().get(normalized_level)
    if isinstance(level, int):
        return normalized_level, level
    return "INFO", logging.INFO


def _redact_sensitive_values(
    _logger: logging.Logger,
    _method_name: str,
    event_dict: MutableMapping[str, Any],
) -> MutableMapping[str, Any]:
    def sanitize(value: Any, *, key_hint: str = "") -> Any:
        normalized_key = key_hint.casefold()
        if any(marker in normalized_key for marker in _SENSITIVE_FIELD_MARKERS):
            return _REDACTED
        if isinstance(value, Mapping):
            return {
                str(key): sanitize(nested, key_hint=str(key))
                for key, nested in value.items()
            }
        if isinstance(value, list):
            return [sanitize(item, key_hint=key_hint) for item in value]
        if isinstance(value, tuple):
            return tuple(sanitize(item, key_hint=key_hint) for item in value)
        return value

    return {
        str(key): sanitize(value, key_hint=str(key))
        for key, value in event_dict.items()
    }


def configure_logging(log_level: str = "INFO", *, http_debug: bool = False) -> None:
    """Configure colored, structured console logging for app and library loggers."""

    _install_trace_level()
    normalized_level, level = _resolve_log_level(log_level)
    requested_colors = _should_use_colors()

    timestamper = structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S", utc=False)
    shared_processors = [
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        timestamper,
        structlog.processors.CallsiteParameterAdder(
            {
                CallsiteParameter.MODULE,
                CallsiteParameter.FUNC_NAME,
                CallsiteParameter.LINENO,
                CallsiteParameter.THREAD_NAME,
                CallsiteParameter.PROCESS,
            }
        ),
        _redact_sensitive_values,
    ]

    console_renderer, colors_enabled, color_fallback_used = _build_console_renderer(
        requested_colors
    )
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            console_renderer,
        ],
    )

    handler = logging.StreamHandler()
    handler.setLevel(level)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(level)
    root_logger.addHandler(handler)

    http_log_level = logging.DEBUG if http_debug else logging.WARNING
    for logger_name in _NOISY_LOGGERS:
        library_logger = logging.getLogger(logger_name)
        if logger_name in {"httpx", "httpcore"}:
            library_logger.setLevel(http_log_level)
        else:
            library_logger.setLevel(max(level, logging.WARNING))

    structlog.reset_defaults()
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            timestamper,
            structlog.processors.CallsiteParameterAdder(
                {
                    CallsiteParameter.MODULE,
                    CallsiteParameter.FUNC_NAME,
                    CallsiteParameter.LINENO,
                    CallsiteParameter.THREAD_NAME,
                    CallsiteParameter.PROCESS,
                }
            ),
            _redact_sensitive_values,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    if color_fallback_used:
        structlog.get_logger(__name__).warning(
            "logging_color_fallback_enabled",
            reason="colorama_missing_on_windows",
            console_colors_requested=requested_colors,
        )

    structlog.get_logger(__name__).info(
        "logging_configured",
        log_level=normalized_level,
        http_debug=http_debug,
        http_log_level=logging.getLevelName(http_log_level),
        console_colors=colors_enabled,
        console_colors_requested=requested_colors,
        formatter="structlog_console",
        trace_enabled=level <= TRACE_LEVEL,
    )


def _build_console_renderer(
    colors_enabled: bool,
) -> tuple[structlog.typing.Processor, bool, bool]:
    try:
        return structlog.dev.ConsoleRenderer(colors=colors_enabled), colors_enabled, False
    except SystemError as exc:
        if colors_enabled and sys.platform == "win32" and "colorama" in str(exc).lower():
            return structlog.dev.ConsoleRenderer(colors=False), False, True
        raise


def _should_use_colors() -> bool:
    if os.getenv("NO_COLOR"):
        return False
    forced = os.getenv("BOM_WORKBENCH_LOG_COLORS", "").strip().lower()
    if forced in {"1", "true", "yes", "always"}:
        return True
    if forced in {"0", "false", "no", "never"}:
        return False
    if os.getenv("FORCE_COLOR"):
        return True
    stream = sys.stderr
    return hasattr(stream, "isatty") and stream.isatty()
