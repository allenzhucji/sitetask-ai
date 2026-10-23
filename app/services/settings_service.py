from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from app.models.settings import Settings
from app.utils.paths import AppPaths


class SettingsService:
    def __init__(self, paths: AppPaths | None = None) -> None:
        self.paths = paths or AppPaths.discover()

    @property
    def settings_file(self) -> Path:
        return self.paths.settings_file

    def load(self) -> Settings:
        self.paths.ensure_runtime_directories()
        if not self.settings_file.exists():
            settings = Settings()
            self.save(settings)
            return settings

        try:
            raw_settings = json.loads(self.settings_file.read_text(encoding="utf-8"))
            settings = Settings.model_validate(raw_settings)
        except (OSError, json.JSONDecodeError, ValidationError, TypeError):
            backup = self._backup_corrupt_settings()
            settings = Settings()
            # Never overwrite an unreadable or invalid file unless its backup succeeded.
            if backup is not None:
                self.save(settings)
            return settings

        # Persist the normalized model so newly introduced defaults are added.
        self.save(settings)
        return settings

    def save(self, settings: Settings) -> bool:
        try:
            self.paths.ensure_runtime_directories()
            temporary_file = self.settings_file.with_suffix(".json.tmp")
            serialized = json.dumps(
                settings.model_dump(mode="json"),
                ensure_ascii=False,
                indent=2,
            )
            temporary_file.write_text(f"{serialized}\n", encoding="utf-8")
            temporary_file.replace(self.settings_file)
        except OSError:
            return False
        return True

    def _backup_corrupt_settings(self) -> Path | None:
        if not self.settings_file.exists():
            return None

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        backup = self.settings_file.with_name(f"settings.corrupt-{timestamp}.json")
        try:
            shutil.copy2(self.settings_file, backup)
        except OSError:
            return None
        return backup
