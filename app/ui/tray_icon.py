from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from app.ui.app_icon import load_app_icon


class TrayIcon(QSystemTrayIcon):
    open_widget_requested = Signal()
    add_task_requested = Signal()
    ai_task_requested = Signal()
    all_tasks_requested = Signal()
    toggle_pin_requested = Signal()
    notifications_paused = Signal(bool)
    settings_requested = Signal()
    exit_requested = Signal()
    toggle_widget_requested = Signal()

    def __init__(self) -> None:
        super().__init__(load_app_icon())
        self.setToolTip("SiteTask AI")

        self.menu = QMenu()
        self.open_action = self._add_action("Open Widget", self.open_widget_requested)
        self.add_task_action = self._add_action("Add Task", self.add_task_requested)
        self.ai_task_action = self._add_action("AI Task Input", self.ai_task_requested)
        self.all_tasks_action = self._add_action(
            "View All Tasks", self.all_tasks_requested
        )
        self.toggle_pin_action = self._add_action("Toggle Pin", self.toggle_pin_requested)
        self.pause_notifications_action = QAction("Pause Notifications", self.menu)
        self.pause_notifications_action.setCheckable(True)
        self.pause_notifications_action.toggled.connect(self.notifications_paused)
        self.menu.addAction(self.pause_notifications_action)
        self.settings_action = self._add_action("Settings", self.settings_requested)
        self.menu.addSeparator()
        self.exit_action = self._add_action("Exit", self.exit_requested)
        self.setContextMenu(self.menu)
        self.activated.connect(self._handle_activation)

    def _add_action(self, label: str, signal) -> QAction:
        action = QAction(label, self.menu)
        action.triggered.connect(lambda _checked=False: signal.emit())
        self.menu.addAction(action)
        return action

    def _handle_activation(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.toggle_widget_requested.emit()
