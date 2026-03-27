from __future__ import annotations

import asyncio
import sys
import types

from bom_workbench.infrastructure.secrets import KeyringSecretStore
import bom_workbench.infrastructure.secrets.keyring_store as keyring_store_module


def test_keyring_secret_store_gracefully_falls_back_when_keyring_missing(monkeypatch) -> None:
    async def scenario() -> None:
        monkeypatch.setattr(keyring_store_module, "import_module", lambda name: (_ for _ in ()).throw(ImportError(name)))
        store = KeyringSecretStore(service_name="test-service")

        assert store.status.available is False
        assert await store.get_key("openai") is None

    asyncio.run(scenario())

def test_keyring_secret_store_gracefully_falls_back_when_backend_unavailable(monkeypatch) -> None:
    async def scenario() -> None:
        fake_keyring = types.SimpleNamespace(
            get_keyring=lambda: (_ for _ in ()).throw(RuntimeError("no backend")),
            set_password=lambda *args, **kwargs: None,
            get_password=lambda *args, **kwargs: None,
            delete_password=lambda *args, **kwargs: None,
        )
        monkeypatch.setitem(sys.modules, "keyring", fake_keyring)
        store = KeyringSecretStore(service_name="test-service")

        assert store.status.available is False
        assert await store.get_key("openai") is None

    asyncio.run(scenario())
