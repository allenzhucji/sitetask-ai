from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Literal, Protocol

import keyring
from keyring.errors import KeyringError, PasswordDeleteError
from pydantic import BaseModel, SecretStr


class KeyringBackend(Protocol):
    def get_password(self, service_name: str, username: str) -> str | None: ...

    def set_password(self, service_name: str, username: str, password: str) -> None: ...

    def delete_password(self, service_name: str, username: str) -> None: ...


class ApiCredential(BaseModel):
    api_key: SecretStr
    source: Literal["keyring", "environment"]


class CredentialService:
    SERVICE_NAME = "SiteTaskAI"
    USERNAME = "openai_api_key"
    ENVIRONMENT_VARIABLE = "OPENAI_API_KEY"

    def __init__(
        self,
        *,
        keyring_backend: KeyringBackend = keyring,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        self.keyring_backend = keyring_backend
        self.environment = environment if environment is not None else os.environ

    def get_credential(self) -> ApiCredential | None:
        keyring_value = self._read_keyring()
        if keyring_value:
            return ApiCredential(
                api_key=SecretStr(keyring_value),
                source="keyring",
            )

        environment_value = self.environment.get(self.ENVIRONMENT_VARIABLE, "").strip()
        if environment_value:
            return ApiCredential(
                api_key=SecretStr(environment_value),
                source="environment",
            )
        return None

    def get_api_key(self) -> str | None:
        credential = self.get_credential()
        return credential.api_key.get_secret_value() if credential else None

    def save_api_key(self, api_key: str) -> bool:
        normalized_key = api_key.strip()
        if not normalized_key:
            raise ValueError("API key must not be empty")
        try:
            self.keyring_backend.set_password(
                self.SERVICE_NAME,
                self.USERNAME,
                normalized_key,
            )
        except (KeyringError, OSError, RuntimeError):
            return False
        return True

    def delete_api_key(self) -> bool:
        try:
            self.keyring_backend.delete_password(
                self.SERVICE_NAME,
                self.USERNAME,
            )
        except PasswordDeleteError:
            return True
        except (KeyringError, OSError, RuntimeError):
            return False
        return True

    def masked_api_key(self) -> str | None:
        api_key = self.get_api_key()
        if api_key is None:
            return None
        if len(api_key) <= 8:
            return "••••"
        return f"{api_key[:3]}••••{api_key[-4:]}"

    def _read_keyring(self) -> str | None:
        try:
            value = self.keyring_backend.get_password(
                self.SERVICE_NAME,
                self.USERNAME,
            )
        except (KeyringError, OSError, RuntimeError):
            return None
        return value.strip() if value and value.strip() else None
