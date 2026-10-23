from __future__ import annotations

from pathlib import Path

from app.services.startup_service import StartupService


class FakeRegistry:
    def __init__(self):
        self.values = {}
        self.set_calls = []
        self.delete_calls = []
        self.error: OSError | None = None

    def get_value(self, key_path, value_name):
        if self.error:
            raise self.error
        return self.values.get((key_path, value_name))

    def set_value(self, key_path, value_name, value):
        if self.error:
            raise self.error
        self.set_calls.append((key_path, value_name, value))
        self.values[(key_path, value_name)] = value

    def delete_value(self, key_path, value_name):
        if self.error:
            raise self.error
        self.delete_calls.append((key_path, value_name))
        self.values.pop((key_path, value_name), None)


def make_service(registry, *, frozen=False):
    return StartupService(
        registry=registry,
        executable_path=Path(r"C:\Program Files\SiteTask Python\python.exe"),
        script_path=Path(r"C:\Example\SiteTask AI\main.py"),
        frozen=frozen,
    )


def test_development_command_uses_pythonw_and_quotes_paths():
    service = make_service(FakeRegistry())

    assert service.command == (
        '"C:\\Program Files\\SiteTask Python\\pythonw.exe" '
        '"C:\\Example\\SiteTask AI\\main.py"'
    )


def test_frozen_command_uses_only_packaged_executable():
    service = StartupService(
        registry=FakeRegistry(),
        executable_path=Path(r"C:\Program Files\SiteTask AI\SiteTaskAI.exe"),
        script_path=Path(r"C:\ignored\main.py"),
        frozen=True,
    )

    assert service.command == '"C:\\Program Files\\SiteTask AI\\SiteTaskAI.exe"'


def test_enable_is_idempotent_and_updates_stale_path():
    registry = FakeRegistry()
    service = make_service(registry)
    key = (service.RUN_KEY, service.VALUE_NAME)
    registry.values[key] = r'"C:\Old Path\SiteTaskAI.exe"'

    assert service.enable()
    assert registry.values[key] == service.command
    assert len(registry.set_calls) == 1
    assert service.enable()
    assert len(registry.set_calls) == 1
    assert service.is_enabled()


def test_disable_is_reversible_and_missing_value_is_not_an_error():
    registry = FakeRegistry()
    service = make_service(registry)

    assert service.enable()
    assert service.disable()
    assert not service.is_enabled()
    assert service.disable()
    assert len(registry.delete_calls) == 2


def test_registry_errors_are_recoverable():
    registry = FakeRegistry()
    service = make_service(registry)
    registry.error = OSError("registry unavailable")

    assert not service.enable()
    assert not service.disable()
    assert not service.is_enabled()
