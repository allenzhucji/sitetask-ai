from __future__ import annotations

import json

from app.services.settings_service import SettingsService
from app.utils.paths import AppPaths


def make_service(tmp_path):
    return SettingsService(AppPaths(tmp_path))


def test_first_load_creates_default_settings(tmp_path):
    service = make_service(tmp_path)

    settings = service.load()

    assert settings.window.width == 400
    assert settings.display.days_ahead == 3
    assert service.settings_file.exists()
    assert (tmp_path / "data").is_dir()
    assert (tmp_path / "logs").is_dir()


def test_missing_fields_are_filled_and_persisted(tmp_path):
    service = make_service(tmp_path)
    service.paths.ensure_runtime_directories()
    service.settings_file.write_text('{"window": {"width": 460}}', encoding="utf-8")

    settings = service.load()
    persisted = json.loads(service.settings_file.read_text(encoding="utf-8"))

    assert settings.window.width == 460
    assert settings.window.height == 700
    assert persisted["display"]["days_ahead"] == 3
    assert persisted["task_defaults"]["default_due_time"] == "17:00"


def test_corrupt_settings_are_backed_up_and_replaced(tmp_path):
    service = make_service(tmp_path)
    service.paths.ensure_runtime_directories()
    service.settings_file.write_text("{not-valid-json", encoding="utf-8")

    settings = service.load()
    backups = list(service.paths.config_dir.glob("settings.corrupt-*.json"))

    assert settings == settings.__class__()
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "{not-valid-json"
    json.loads(service.settings_file.read_text(encoding="utf-8"))


def test_window_state_is_saved(tmp_path):
    service = make_service(tmp_path)
    settings = service.load()
    settings.window.width = 520
    settings.window.height = 760
    settings.window.x = 120
    settings.window.y = 80
    settings.window.is_pinned = True

    assert service.save(settings)
    reloaded = service.load()

    assert reloaded.window.model_dump() == settings.window.model_dump()


def test_default_time_is_saved(tmp_path):
    service = make_service(tmp_path)
    settings = service.load()
    settings.task_defaults.default_due_time = "16:30"
    settings.task_defaults.apply_default_time = False

    assert service.save(settings)
    reloaded = service.load()

    assert reloaded.task_defaults.default_due_time == "16:30"
    assert reloaded.task_defaults.apply_default_time is False
