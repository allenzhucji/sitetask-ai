from __future__ import annotations

from keyring.errors import KeyringError, PasswordDeleteError

from app.services.credential_service import CredentialService
from app.services.settings_service import SettingsService
from app.utils.paths import AppPaths


class FakeKeyring:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}
        self.read_error: Exception | None = None
        self.write_error: Exception | None = None
        self.delete_error: Exception | None = None

    def get_password(self, service_name: str, username: str) -> str | None:
        if self.read_error:
            raise self.read_error
        return self.values.get((service_name, username))

    def set_password(self, service_name: str, username: str, password: str) -> None:
        if self.write_error:
            raise self.write_error
        self.values[(service_name, username)] = password

    def delete_password(self, service_name: str, username: str) -> None:
        if self.delete_error:
            raise self.delete_error
        key = (service_name, username)
        if key not in self.values:
            raise PasswordDeleteError("missing")
        del self.values[key]


def test_keyring_uses_required_identity_and_has_read_priority():
    backend = FakeKeyring()
    backend.values[("SiteTaskAI", "openai_api_key")] = "test-keyring-value"
    service = CredentialService(
        keyring_backend=backend,
        environment={"OPENAI_API_KEY": "test-environment-value"},
    )

    credential = service.get_credential()

    assert credential is not None
    assert credential.source == "keyring"
    assert credential.api_key.get_secret_value() == "test-keyring-value"
    assert "test-keyring-value" not in repr(credential)


def test_environment_is_used_when_keyring_is_empty_or_unavailable():
    backend = FakeKeyring()
    service = CredentialService(
        keyring_backend=backend,
        environment={"OPENAI_API_KEY": "  test-environment-value  "},
    )
    assert service.get_api_key() == "test-environment-value"
    assert service.get_credential().source == "environment"

    backend.read_error = KeyringError("backend unavailable")
    assert service.get_api_key() == "test-environment-value"


def test_unconfigured_credentials_return_none():
    service = CredentialService(keyring_backend=FakeKeyring(), environment={})

    assert service.get_credential() is None
    assert service.get_api_key() is None
    assert service.masked_api_key() is None


def test_save_and_delete_only_mutate_keyring():
    backend = FakeKeyring()
    environment = {"OPENAI_API_KEY": "test-environment-value"}
    service = CredentialService(keyring_backend=backend, environment=environment)

    assert service.save_api_key("  test-saved-value  ")
    assert backend.values[("SiteTaskAI", "openai_api_key")] == "test-saved-value"
    assert environment["OPENAI_API_KEY"] == "test-environment-value"
    assert service.get_api_key() == "test-saved-value"

    assert service.delete_api_key()
    assert service.get_api_key() == "test-environment-value"


def test_missing_delete_is_idempotent_and_backend_failures_are_recoverable():
    backend = FakeKeyring()
    service = CredentialService(keyring_backend=backend, environment={})
    assert service.delete_api_key()

    backend.write_error = KeyringError("write failed")
    assert not service.save_api_key("test-never-stored")
    backend.delete_error = KeyringError("delete failed")
    assert not service.delete_api_key()


def test_empty_key_is_rejected_without_mutation():
    backend = FakeKeyring()
    service = CredentialService(keyring_backend=backend, environment={})

    try:
        service.save_api_key("   ")
    except ValueError as error:
        assert str(error) == "API key must not be empty"
    else:
        raise AssertionError("Expected empty API key to be rejected")
    assert backend.values == {}


def test_masking_never_returns_the_full_secret():
    secret = "test-credential-abcdefghijklmno"
    backend = FakeKeyring()
    backend.values[("SiteTaskAI", "openai_api_key")] = secret
    service = CredentialService(keyring_backend=backend, environment={})

    masked = service.masked_api_key()

    assert masked == "tes••••lmno"
    assert secret not in masked


def test_api_key_is_not_written_to_settings_json(tmp_path):
    secret = "test-do-not-write-to-json"
    backend = FakeKeyring()
    credentials = CredentialService(keyring_backend=backend, environment={})
    settings_service = SettingsService(AppPaths(tmp_path))
    settings_service.load()

    assert credentials.save_api_key(secret)

    settings_text = settings_service.settings_file.read_text(encoding="utf-8")
    assert secret not in settings_text
    assert "OPENAI_API_KEY" not in settings_text
