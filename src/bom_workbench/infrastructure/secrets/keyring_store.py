"""Keyring-backed secret storage with graceful fallback."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import Any

from ...domain.ports import ISecretStore

__all__ = ["KeyringSecretStore", "SecretStoreStatus"]


@dataclass(slots=True, frozen=True)
class SecretStoreStatus:
    """Report whether the secret store is backed by a usable keyring."""

    available: bool
    backend_name: str = ""
    message: str = ""


class KeyringSecretStore(ISecretStore):
    """Persist provider keys in the active OS keyring when available."""

    def __init__(self, *, service_name: str = "bom-workbench") -> None:
        self._service_name = service_name
        self._keyring = self._load_keyring()
        self._status = self._build_status()

    @property
    def status(self) -> SecretStoreStatus:
        return self._status

    async def store_key(self, provider: str, api_key: str) -> None:
        if self._keyring is None:
            return
        self._safe_call("set_password", self._service_name, self._secret_name(provider), api_key)

    async def get_key(self, provider: str) -> str | None:
        if self._keyring is None:
            return None
        value = self._safe_call("get_password", self._service_name, self._secret_name(provider))
        return value if isinstance(value, str) else None

    async def delete_key(self, provider: str) -> None:
        if self._keyring is None:
            return
        self._safe_call("delete_password", self._service_name, self._secret_name(provider))

    def _load_keyring(self) -> Any | None:
        try:
            keyring = import_module("keyring")
        except Exception:
            return None

        try:
            backend = keyring.get_keyring()
        except Exception:
            return None

        backend_name = getattr(backend, "__class__", type(backend)).__name__.lower()
        if "fail" in backend_name or "null" in backend_name:
            return None
        return keyring

    def _build_status(self) -> SecretStoreStatus:
        if self._keyring is None:
            return SecretStoreStatus(available=False, message="keyring backend unavailable")
        try:
            backend = self._keyring.get_keyring()
            backend_name = backend.__class__.__name__
        except Exception:
            return SecretStoreStatus(available=False, message="keyring backend unavailable")
        return SecretStoreStatus(available=True, backend_name=backend_name, message="keyring backend ready")

    def _secret_name(self, provider: str) -> str:
        normalized = provider.strip().lower().replace(" ", "-")
        return f"{normalized}:api-key"

    def _safe_call(self, method_name: str, *args: Any) -> Any:
        assert self._keyring is not None
        try:
            method = getattr(self._keyring, method_name)
            return method(*args)
        except Exception:
            return None
