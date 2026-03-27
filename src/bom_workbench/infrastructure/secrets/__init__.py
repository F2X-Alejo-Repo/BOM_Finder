"""Secret storage infrastructure adapters."""

from __future__ import annotations

from .keyring_store import KeyringSecretStore, SecretStoreStatus

__all__ = ["KeyringSecretStore", "SecretStoreStatus"]
