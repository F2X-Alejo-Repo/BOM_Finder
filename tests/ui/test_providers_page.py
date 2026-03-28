"""Focused UI tests for the providers page contract."""

from __future__ import annotations

import pytest


def _ensure_app(monkeypatch: pytest.MonkeyPatch):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")

    from PySide6 import QtWidgets

    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(["bom-workbench-test"])
    return app


def test_providers_page_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    """The providers page should expose the Phase 7 UI contract."""
    _ensure_app(monkeypatch)

    from bom_workbench.ui.pages.providers_page import (
        ProviderCapabilities,
        ProvidersPage,
    )

    page = ProvidersPage()

    openai_card = page._provider_cards["openai"]
    anthropic_card = page._provider_cards["anthropic"]

    page.set_provider_models("openai", ["gpt-4.1-mini", "gpt-5"])
    page.set_provider_models("anthropic", ["claude-sonnet-4", "claude-haiku-4"])
    page.set_provider_api_key("openai", "sk-detected")
    page.set_connection_status_text("openai", "Connected")
    page.apply_provider_capabilities(
        "anthropic",
        ProviderCapabilities(show_reasoning_controls=False),
    )

    assert openai_card.model.count() == 2
    assert openai_card.model.itemText(0) == "gpt-4.1-mini"
    assert openai_card.api_key.text() == "sk-detected"
    assert openai_card.connection_status_value.text() == "Connected"
    assert anthropic_card.reasoning_group.isHidden()

    test_events: list[tuple[str, str]] = []
    refresh_events: list[tuple[str, str]] = []
    save_events: list[dict[str, dict[str, object]]] = []

    page.test_connection_clicked.connect(
        lambda provider, api_key: test_events.append((provider, api_key))
    )
    page.refresh_models_clicked.connect(
        lambda provider, api_key: refresh_events.append((provider, api_key))
    )
    page.save_settings_clicked.connect(save_events.append)

    openai_card.api_key.setText("openai-key")
    anthropic_card.api_key.setText("anthropic-key")
    openai_card.test_button.click()
    anthropic_card.refresh_button.click()
    page.save_button.click()

    assert test_events == [("openai", "openai-key")]
    assert refresh_events == [("anthropic", "anthropic-key")]
    assert save_events
    payload = save_events[0]
    assert payload["openai"]["api_key"] == "openai-key"
    assert payload["anthropic"]["api_key"] == "anthropic-key"
    assert payload["openai"]["selected_model"] == "gpt-4.1-mini"

    page.hydrate_provider_settings(
        "openai",
        {
            "provider": "openai",
            "enabled": False,
            "selected_model": "gpt-5",
            "reasoning_mode": "Medium",
            "cached_models": ["gpt-4.1-mini", "gpt-5"],
            "timeout_seconds": 90,
            "max_retries": 4,
            "max_concurrent": 2,
            "temperature": 0.2,
            "privacy_level": "minimal",
            "manual_approval": True,
            "auth_method": "api_key",
            "extra_config": {"profile": "prod"},
        },
    )

    hydrated_payload = page.provider_settings()["openai"]
    assert openai_card.enabled.isChecked() is False
    assert openai_card.model.currentText() == "gpt-5"
    assert openai_card.reasoning_mode.currentText() == "Medium"
    assert hydrated_payload["selected_model"] == "gpt-5"
    assert hydrated_payload["reasoning_mode"] == "Medium"
    assert hydrated_payload["cached_models"] == ["gpt-4.1-mini", "gpt-5"]
    assert hydrated_payload["runtime_defaults"]["timeout_seconds"] == 90
    assert hydrated_payload["runtime_defaults"]["max_retries"] == 4
    assert hydrated_payload["runtime_defaults"]["max_concurrent"] == 2
    assert hydrated_payload["runtime_defaults"]["manual_approval"] is True
