"""Validate the packaged Qt loader, preventing an incompatible ICU DLL shadow."""
from __future__ import annotations

import argparse
import ctypes
from datetime import datetime
import json
import os
from pathlib import Path
import shutil

import pefile


def imports_from(path: Path, name: bytes) -> set[str]:
    with pefile.PE(str(path), fast_load=True) as pe:
        pe.parse_data_directories(directories=[1])
        return {item.name.decode() for dependency in getattr(pe, "DIRECTORY_ENTRY_IMPORT", [])
                if dependency.dll.lower() == name for item in dependency.imports if item.name}


def exports(path: Path) -> set[str]:
    with pefile.PE(str(path), fast_load=True) as pe:
        pe.parse_data_directories(directories=[0])
        return {item.name.decode() for item in pe.DIRECTORY_ENTRY_EXPORT.symbols if item.name}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--repair", action="store_true")
    args = parser.parse_args()
    bundle = args.bundle.resolve()
    internal = bundle / "_internal"
    core = internal / "PySide6/Qt6Core.dll"
    required = imports_from(core, b"icuuc.dll")
    bundled = internal / "icuuc.dll"
    system = Path(os.environ["SystemRoot"]) / "System32/icuuc.dll"
    moved = []
    if required and bundled.exists() and required - exports(bundled):
        if not args.repair:
            raise RuntimeError("Packaged icuuc.dll lacks QtCore entry points; run --repair on a stopped/staged bundle")
        if required - exports(system):
            raise RuntimeError("System ICU is also incompatible; nothing was changed")
        # Never discard another dependency's required ICU. Ignore only this
        # incompatible ICU's own data DLL dependency; preserve it as a backup.
        for binary in internal.rglob("*"):
            if binary.suffix.lower() in {".dll", ".pyd"} and binary not in {bundled, core}:
                if imports_from(binary, b"icuuc.dll") or imports_from(binary, b"icudt78.dll"):
                    raise RuntimeError(f"Another binary depends on packaged ICU: {binary.name}")
        quarantine = bundle.parent / ("icu-quarantine-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
        quarantine.mkdir(exist_ok=False)
        for name in ("icuuc.dll", "icudt78.dll"):
            source = internal / name
            if source.exists():
                destination = quarantine / name
                shutil.move(str(source), str(destination))
                moved.append(str(destination))
    elif required and not bundled.exists() and required - exports(system):
        raise RuntimeError("System ICU lacks required QtCore entry points")
    # Fail as a console error, never show native loader dialogs during a build.
    ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002 | 0x8000)
    directories = [internal, internal / "PySide6", internal / "shiboken6"]
    handles = [os.add_dll_directory(str(p)) for p in directories]
    loaded = [ctypes.WinDLL(str(core)), ctypes.WinDLL(str(internal / "PySide6/QtCore.pyd"))]
    assert handles and loaded
    print(json.dumps({"result": "QtCore loader OK", "bundle": str(bundle), "quarantined": moved,
                      "icu_required_exports": len(required)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
