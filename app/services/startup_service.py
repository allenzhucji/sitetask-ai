from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Protocol


class RegistryBackend(Protocol):
    def get_value(self, key_path: str, value_name: str) -> str | None: ...

    def set_value(self, key_path: str, value_name: str, value: str) -> None: ...

    def delete_value(self, key_path: str, value_name: str) -> None: ...


class WindowsRegistryBackend:
    def get_value(self, key_path: str, value_name: str) -> str | None:
        import winreg

        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                key_path,
                0,
                winreg.KEY_QUERY_VALUE,
            ) as key:
                value, _ = winreg.QueryValueEx(key, value_name)
        except FileNotFoundError:
            return None
        return str(value)

    def set_value(self, key_path: str, value_name: str, value: str) -> None:
        import winreg

        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER,
            key_path,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.SetValueEx(key, value_name, 0, winreg.REG_SZ, value)

    def delete_value(self, key_path: str, value_name: str) -> None:
        import winreg

        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                key_path,
                0,
                winreg.KEY_SET_VALUE,
            ) as key:
                winreg.DeleteValue(key, value_name)
        except FileNotFoundError:
            return


class StartupService:
    RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
    VALUE_NAME = "SiteTaskAI"

    def __init__(
        self,
        *,
        registry: RegistryBackend | None = None,
        executable_path: Path | None = None,
        script_path: Path | None = None,
        frozen: bool | None = None,
        value_name: str = VALUE_NAME,
    ) -> None:
        self.registry = registry or WindowsRegistryBackend()
        self.executable_path = Path(executable_path or sys.executable).resolve()
        self.script_path = Path(
            script_path or Path(__file__).resolve().parents[2] / "main.py"
        ).resolve()
        self.frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
        self.value_name = value_name

    @property
    def command(self) -> str:
        if self.frozen:
            arguments = [str(self.executable_path)]
        else:
            pythonw = self.executable_path.with_name("pythonw.exe")
            arguments = [str(pythonw), str(self.script_path)]
        return subprocess.list2cmdline(arguments)

    def is_enabled(self) -> bool:
        try:
            return self.registry.get_value(self.RUN_KEY, self.value_name) == self.command
        except OSError:
            return False

    def enable(self) -> bool:
        try:
            if self.registry.get_value(self.RUN_KEY, self.value_name) == self.command:
                return True
            self.registry.set_value(self.RUN_KEY, self.value_name, self.command)
        except OSError:
            return False
        return True

    def disable(self) -> bool:
        try:
            self.registry.delete_value(self.RUN_KEY, self.value_name)
        except OSError:
            return False
        return True

    def apply(self, enabled: bool) -> bool:
        return self.enable() if enabled else self.disable()
