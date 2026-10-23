from __future__ import annotations

from PySide6.QtCore import QPoint, QSize, Qt

from app.services.settings_service import SettingsService
from app.ui.main_widget import MainWidget
from app.utils.paths import AppPaths


def make_widget(tmp_path) -> MainWidget:
    return MainWidget(SettingsService(AppPaths(tmp_path)))


def assert_geometry(widget: MainWidget, position: QPoint, size: QSize) -> None:
    assert widget.pos() == position
    assert widget.size() == size


def test_normal_to_pinned_preserves_window_state(qtbot, tmp_path):
    widget = make_widget(tmp_path)
    qtbot.addWidget(widget)
    widget.show()
    widget.move(180, 140)
    widget.resize(520, 760)
    position = widget.pos()
    size = widget.size()

    widget.set_pinned(True)

    assert widget.isVisible()
    assert widget.is_pinned is True
    assert widget.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    assert widget.title_bar.pin_button.isChecked()
    assert_geometry(widget, position, size)


def test_pinned_to_normal_and_repeated_toggles_preserve_geometry(qtbot, tmp_path):
    widget = make_widget(tmp_path)
    qtbot.addWidget(widget)
    widget.show()
    widget.move(210, 165)
    widget.resize(480, 680)
    position = widget.pos()
    size = widget.size()

    for pinned in (True, False, True, False):
        widget.set_pinned(pinned)
        assert widget.isVisible()
        assert widget.is_pinned is pinned
        assert bool(widget.windowFlags() & Qt.WindowType.WindowStaysOnTopHint) is pinned
        assert widget.title_bar.pin_button.isChecked() is pinned
        assert_geometry(widget, position, size)


def test_pin_and_geometry_are_restored_after_restart(qtbot, tmp_path):
    service = SettingsService(AppPaths(tmp_path))
    first = MainWidget(service)
    qtbot.addWidget(first)
    first.show()
    first.move(240, 190)
    first.resize(500, 720)
    first.set_pinned(True)
    saved_position = first.pos()
    saved_size = first.size()
    first.close()

    restarted = MainWidget(service)
    qtbot.addWidget(restarted)

    assert restarted.is_pinned is True
    assert restarted.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    assert restarted.title_bar.pin_button.isChecked()
    assert_geometry(restarted, saved_position, saved_size)


def test_pin_button_toggles_without_creating_another_window(qtbot, tmp_path):
    widget = make_widget(tmp_path)
    qtbot.addWidget(widget)
    widget.show()
    identity = id(widget)

    qtbot.mouseClick(widget.title_bar.pin_button, Qt.MouseButton.LeftButton)
    assert id(widget) == identity
    assert widget.is_pinned is True

    qtbot.mouseClick(widget.title_bar.pin_button, Qt.MouseButton.LeftButton)
    assert id(widget) == identity
    assert widget.is_pinned is False
