"""Tests for centralized logging configuration."""

from __future__ import annotations

import logging

import pytest
import structlog

import bom_workbench.logging_config as logging_config
from bom_workbench.logging_config import TRACE_LEVEL, configure_logging


def test_configure_logging_sets_root_and_http_levels() -> None:
    """Logging config should apply root and HTTP logger verbosity."""

    configure_logging("DEBUG", http_debug=True)

    root_logger = logging.getLogger()
    assert root_logger.level == logging.DEBUG
    assert root_logger.handlers
    assert logging.getLogger("httpx").level == logging.DEBUG
    assert logging.getLogger("httpcore").level == logging.DEBUG


def test_configure_logging_supports_trace_level() -> None:
    """Trace should be accepted as the most verbose console level."""

    configure_logging("TRACE", http_debug=False)

    root_logger = logging.getLogger()
    assert root_logger.level == TRACE_LEVEL
    assert hasattr(structlog.get_logger(__name__), "info")


def test_configure_logging_redacts_sensitive_values(capsys: pytest.CaptureFixture[str]) -> None:
    """Sensitive logging fields should be redacted before rendering."""

    configure_logging("INFO", http_debug=False)

    structlog.get_logger("tests.logging").info(
        "provider_settings_saved",
        provider="openai",
        api_key="sk-secret-value",
        nested={"authorization": "Bearer abc123"},
    )

    captured = capsys.readouterr()
    assert "***REDACTED***" in captured.err
    assert "sk-secret-value" not in captured.err
    assert "Bearer abc123" not in captured.err


def test_configure_logging_accepts_invalid_level_with_info_fallback() -> None:
    """Invalid levels should fall back to INFO without crashing."""

    configure_logging("NOT_A_LEVEL", http_debug=False)

    root_logger = logging.getLogger()
    assert root_logger.level == logging.INFO
    assert logging.getLogger("httpx").level == logging.WARNING
    assert root_logger.handlers[0].formatter is not None


def test_configure_logging_disables_colors_when_colorama_is_missing_on_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Windows color rendering should fall back instead of crashing."""

    class FakeConsoleRenderer:
        def __init__(self, *, colors: bool) -> None:
            if colors:
                msg = (
                    "ConsoleRenderer with `colors=True` on Windows "
                    "requires the colorama package installed."
                )
                raise SystemError(msg)
            self.colors = colors

        def __call__(
            self,
            _logger: logging.Logger,
            _method_name: str,
            event_dict: structlog.typing.EventDict,
        ) -> str:
            return str(event_dict)

    monkeypatch.setattr(logging_config, "_should_use_colors", lambda: True)
    monkeypatch.setattr(logging_config.sys, "platform", "win32")
    monkeypatch.setattr(logging_config.structlog.dev, "ConsoleRenderer", FakeConsoleRenderer)

    configure_logging("INFO", http_debug=False)

    root_logger = logging.getLogger()
    formatter = root_logger.handlers[0].formatter
    assert formatter is not None
    renderer = formatter.processors[-1]
    assert isinstance(renderer, FakeConsoleRenderer)
    assert renderer.colors is False
