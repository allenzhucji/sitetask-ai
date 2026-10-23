from __future__ import annotations

from typing import Literal

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap


IconName = Literal[
    "pin",
    "tasks",
    "settings",
    "minimize",
    "close",
    "chevron_left",
    "chevron_right",
]


def make_flat_icon(name: IconName, *, checkable: bool = False) -> QIcon:
    icon = QIcon()
    states = (
        (QIcon.Mode.Normal, QIcon.State.Off, QColor("#b8c0cc")),
        (QIcon.Mode.Active, QIcon.State.Off, QColor("#ffffff")),
    )
    for mode, state, color in states:
        icon.addPixmap(_draw_icon(name, color), mode, state)
    if checkable:
        checked = QColor("#ffffff")
        icon.addPixmap(_draw_icon(name, checked), QIcon.Mode.Normal, QIcon.State.On)
        icon.addPixmap(_draw_icon(name, checked), QIcon.Mode.Active, QIcon.State.On)
    return icon


def _draw_icon(name: IconName, color: QColor) -> QPixmap:
    pixmap = QPixmap(36, 36)
    pixmap.setDevicePixelRatio(2.0)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(
        QPen(
            color,
            1.5,
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
            Qt.PenJoinStyle.RoundJoin,
        )
    )

    if name == "pin":
        path = QPainterPath(QPointF(6.0, 4.0))
        path.lineTo(12.0, 4.0)
        path.moveTo(7.0, 4.0)
        path.lineTo(7.0, 8.3)
        path.lineTo(5.7, 9.7)
        path.lineTo(12.3, 9.7)
        path.lineTo(11.0, 8.3)
        path.lineTo(11.0, 4.0)
        path.moveTo(9.0, 9.7)
        path.lineTo(9.0, 15.0)
        painter.drawPath(path)
    elif name == "tasks":
        painter.drawRoundedRect(QRectF(4.5, 5.0, 8.5, 9.0), 1.0, 1.0)
        painter.drawRoundedRect(QRectF(7.0, 3.5, 7.0, 8.0), 1.0, 1.0)
    elif name == "settings":
        center = QPointF(9.0, 9.0)
        painter.drawEllipse(center, 2.4, 2.4)
        painter.drawEllipse(center, 5.2, 5.2)
        for start, end in (
            ((9, 2), (9, 4)),
            ((9, 14), (9, 16)),
            ((2, 9), (4, 9)),
            ((14, 9), (16, 9)),
            ((4.1, 4.1), (5.4, 5.4)),
            ((12.6, 12.6), (13.9, 13.9)),
            ((13.9, 4.1), (12.6, 5.4)),
            ((5.4, 12.6), (4.1, 13.9)),
        ):
            painter.drawLine(QPointF(*start), QPointF(*end))
    elif name == "minimize":
        # 横线放在 18x18 逻辑画布垂直中心（y=9）；原来 11.5 偏下 2.5px
        painter.drawLine(QPointF(4.5, 9.0), QPointF(13.5, 9.0))
    elif name == "close":
        painter.drawLine(QPointF(5.0, 5.0), QPointF(13.0, 13.0))
        painter.drawLine(QPointF(13.0, 5.0), QPointF(5.0, 13.0))
    elif name == "chevron_left":
        painter.drawLine(QPointF(11.0, 4.5), QPointF(6.5, 9.0))
        painter.drawLine(QPointF(6.5, 9.0), QPointF(11.0, 13.5))
    elif name == "chevron_right":
        painter.drawLine(QPointF(7.0, 4.5), QPointF(11.5, 9.0))
        painter.drawLine(QPointF(11.5, 9.0), QPointF(7.0, 13.5))

    painter.end()
    return pixmap
