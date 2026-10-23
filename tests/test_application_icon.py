from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtGui import QIcon, QImage

from app.application import configure_application_style
from app.ui.app_icon import APP_ICON_ICO_FILE, APP_ICON_PNG_FILE, load_app_icon
from app.ui.tray_icon import TrayIcon


def test_icon_assets_have_transparency_and_windows_sizes(qapp):
    image = QImage(str(APP_ICON_PNG_FILE))
    windows_icon = QIcon(str(APP_ICON_ICO_FILE))

    assert APP_ICON_PNG_FILE.is_file()
    assert APP_ICON_ICO_FILE.is_file()
    assert image.size() == QSize(512, 512)
    assert image.hasAlphaChannel()
    assert all(
        image.pixelColor(x, y).alpha() == 0
        for x, y in ((0, 0), (511, 0), (0, 511), (511, 511))
    )
    assert not windows_icon.isNull()
    available_sizes = set(windows_icon.availableSizes())
    assert {QSize(16, 16), QSize(32, 32), QSize(48, 48), QSize(256, 256)} <= available_sizes


def test_application_and_tray_use_shared_icon(qapp, qtbot):
    configure_application_style(qapp)
    tray = TrayIcon()
    qtbot.addWidget(tray.menu)

    assert not load_app_icon().isNull()
    assert not qapp.windowIcon().isNull()
    assert not tray.icon().isNull()
