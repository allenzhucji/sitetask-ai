from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path


def default_app_root() -> Path:
    """Return the project root in development or executable folder when frozen."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


@dataclass(frozen=True, slots=True)
class AppPaths:
    root: Path

    @classmethod
    def discover(cls) -> "AppPaths":
        return cls(default_app_root())

    @property
    def config_dir(self) -> Path:
        return self.root / "config"

    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    @property
    def settings_file(self) -> Path:
        return self.config_dir / "settings.json"

    @property
    def database_file(self) -> Path:
        return self.data_dir / "sitetask.db"

    def ensure_runtime_directories(self) -> None:
        for directory in (self.config_dir, self.data_dir, self.logs_dir):
            directory.mkdir(parents=True, exist_ok=True)
