from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap


ICON_DIRECTORY = Path(__file__).resolve().parents[1] / "resources" / "icons"
APP_ICON_PNG_FILE = ICON_DIRECTORY / "sitetask-icon.png"
APP_ICON_ICO_FILE = ICON_DIRECTORY / "sitetask-icon.ico"


def load_app_icon() -> QIcon:
    icon = QIcon(str(APP_ICON_PNG_FILE))
    if not icon.isNull():
        return icon

    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor("#3c6e71"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(4, 4, 56, 56, 12, 12)
    painter.setPen(QColor("#ffffff"))
    font = painter.font()
    font.setBold(True)
    font.setPixelSize(34)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "S")
    painter.end()
    return QIcon(pixmap)
