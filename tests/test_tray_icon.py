from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSystemTrayIcon

from app.services.settings_service import SettingsService
from app.ui.main_widget import MainWidget
from app.ui.tray_icon import TrayIcon
from app.utils.paths import AppPaths


def test_tray_menu_contains_required_actions(qtbot):
    tray = TrayIcon()
    labels = [action.text() for action in tray.menu.actions() if not action.isSeparator()]

    assert labels == [
        "Open Widget",
        "Add Task",
        "AI Task Input",
        "View All Tasks",
        "Toggle Pin",
        "Pause Notifications",
        "Settings",
        "Exit",
    ]
    assert tray.ai_task_action.isEnabled()
    assert tray.pause_notifications_action.isCheckable()


def test_tray_actions_and_single_click_emit_requests(qtbot):
    tray = TrayIcon()
    emitted: list[object] = []
    tray.open_widget_requested.connect(lambda: emitted.append("open"))
    tray.ai_task_requested.connect(lambda: emitted.append("ai"))
    tray.notifications_paused.connect(lambda paused: emitted.append(paused))
    tray.toggle_widget_requested.connect(lambda: emitted.append("toggle"))

    tray.open_action.trigger()
    tray.ai_task_action.trigger()
    tray.pause_notifications_action.setChecked(True)
    tray._handle_activation(QSystemTrayIcon.ActivationReason.Trigger)

    assert emitted == ["open", "ai", True, "toggle"]


def test_tray_double_click_does_not_toggle_a_second_time(qtbot):
    tray = TrayIcon()
    emitted: list[str] = []
    tray.toggle_widget_requested.connect(lambda: emitted.append("toggle"))

    tray._handle_activation(QSystemTrayIcon.ActivationReason.Trigger)
    tray._handle_activation(QSystemTrayIcon.ActivationReason.DoubleClick)

    assert emitted == ["toggle"]


def test_close_minimize_open_and_single_click_use_same_widget(qtbot, tmp_path):
    widget = MainWidget(SettingsService(AppPaths(tmp_path)))
    qtbot.addWidget(widget)
    widget.set_tray_available(True)
    widget.show()
    identity = id(widget)

    qtbot.mouseClick(widget.title_bar.minimize_button, Qt.MouseButton.LeftButton)
    assert not widget.isVisible()

    widget.show_from_tray()
    assert widget.isVisible()
    assert id(widget) == identity

    qtbot.mouseClick(widget.title_bar.close_button, Qt.MouseButton.LeftButton)
    assert not widget.isVisible()

    widget.toggle_from_tray()
    assert widget.isVisible()
    widget.toggle_from_tray()
    assert not widget.isVisible()


def test_toggle_pin_and_pause_notifications_are_wired_without_new_window(
    qtbot,
    tmp_path,
):
    widget = MainWidget(SettingsService(AppPaths(tmp_path)))
    tray = TrayIcon()
    qtbot.addWidget(widget)
    identity = id(widget)
    tray.toggle_pin_requested.connect(lambda: widget.set_pinned(not widget.is_pinned))
    tray.notifications_paused.connect(widget.set_notifications_paused)

    tray.toggle_pin_action.trigger()
    tray.pause_notifications_action.setChecked(True)

    assert widget.is_pinned
    assert widget.notifications_paused
    assert id(widget) == identity
