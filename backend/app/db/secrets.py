"""The credential-store contract and its keyring-backed implementation."""

from __future__ import annotations

from typing import Protocol


class SecretStore(Protocol):
    """A minimal view of the operating-system credential store."""

    def get_password(self, service: str, username: str) -> str | None: ...

    def set_password(self, service: str, username: str, password: str) -> None: ...

    def delete_password(self, service: str, username: str) -> None: ...


class KeyringSecrets:
    """Delegates to the `keyring` package, importing it lazily so tests can inject a fake."""

    def get_password(self, service: str, username: str) -> str | None:
        import keyring

        return keyring.get_password(service, username)

    def set_password(self, service: str, username: str, password: str) -> None:
        import keyring

        keyring.set_password(service, username, password)

    def delete_password(self, service: str, username: str) -> None:
        import keyring

        keyring.delete_password(service, username)
