from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent

from app.services.settings_service import SettingsService
from app.ui.main_widget import MainWidget
from app.utils.paths import AppPaths


def make_widget(tmp_path) -> MainWidget:
    return MainWidget(SettingsService(AppPaths(tmp_path)))


def mouse_event(
    event_type: QEvent.Type,
    local_position: QPoint,
    global_position: QPoint,
    button: Qt.MouseButton,
    buttons: Qt.MouseButton,
) -> QMouseEvent:
    return QMouseEvent(
        event_type,
        QPointF(local_position),
        QPointF(global_position),
        button,
        buttons,
        Qt.KeyboardModifier.NoModifier,
    )


def test_main_widget_is_frameless_and_uses_expected_geometry(qtbot, tmp_path):
    widget = make_widget(tmp_path)
    qtbot.addWidget(widget)
    widget.show()

    assert widget.windowFlags() & Qt.WindowType.FramelessWindowHint
    assert widget.size().width() == 400
    assert widget.size().height() == 700
    assert widget.minimumWidth() == 340
    assert widget.minimumHeight() == 480
    assert widget.title_bar.title_label.text() == "SiteTask AI"


def test_title_bar_drag_moves_the_existing_window(qtbot, tmp_path):
    widget = make_widget(tmp_path)
    qtbot.addWidget(widget)
    widget.move(100, 100)
    widget.show()

    local_start = QPoint(40, 20)
    global_start = widget.title_bar.mapToGlobal(local_start)
    delta = QPoint(75, 55)

    widget.title_bar.mousePressEvent(
        mouse_event(
            QEvent.Type.MouseButtonPress,
            local_start,
            global_start,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
        )
    )
    widget.title_bar.mouseMoveEvent(
        mouse_event(
            QEvent.Type.MouseMove,
            local_start + delta,
            global_start + delta,
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
        )
    )
    widget.title_bar.mouseReleaseEvent(
        mouse_event(
            QEvent.Type.MouseButtonRelease,
            local_start + delta,
            global_start + delta,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
        )
    )

    assert widget.pos() == QPoint(175, 155)
    assert widget.title_bar._drag_offset is None


def test_title_bar_buttons_minimize_and_close(qtbot, tmp_path):
    widget = make_widget(tmp_path)
    qtbot.addWidget(widget)
    widget.show()

    qtbot.mouseClick(widget.title_bar.minimize_button, Qt.MouseButton.LeftButton)
    assert widget.isMinimized()

    widget.showNormal()
    qtbot.mouseClick(widget.title_bar.close_button, Qt.MouseButton.LeftButton)
    assert not widget.isVisible()
