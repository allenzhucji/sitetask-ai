from __future__ import annotations

import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QSystemTrayIcon
from qfluentwidgets import Theme
from qfluentwidgets.common.config import qconfig

from app.services.logging_service import (
    configure_logging,
    install_global_exception_handler,
)
from app.services.notification_service import NotificationService
from app.ui.app_icon import load_app_icon
from app.ui.main_widget import MainWidget
from app.ui.tray_icon import TrayIcon


STYLE_FILE = Path(__file__).resolve().parent / "resources" / "styles" / "dark.qss"


def load_application_stylesheet(style_file: Path = STYLE_FILE) -> str:
    try:
        stylesheet = style_file.read_text(encoding="utf-8")
    except OSError:
        return ""
    icon_dir = style_file.parent.parent / "icons"
    replacements = {
        "@CHECK_ICON@": icon_dir / "check.svg",
        "@ARROW_UP_ICON@": icon_dir / "arrow-up-white.png",
        "@ARROW_DOWN_ICON@": icon_dir / "arrow-down-white.png",
        "@ARROW_UP_GRAY_ICON@": icon_dir / "arrow-up-gray.png",
        "@ARROW_DOWN_GRAY_ICON@": icon_dir / "arrow-down-gray.png",
    }
    for placeholder, icon_path in replacements.items():
        stylesheet = stylesheet.replace(placeholder, icon_path.resolve().as_posix())
    return stylesheet


def configure_application_style(application: QApplication) -> None:
    application.setStyle("Fusion")
    application.setStyleSheet(load_application_stylesheet())
    # 深色主题须在控件构造前设置，否则 Fluent 组件用浅色配色。
    # 不用 setTheme()：它会遍历全局 styleSheetManager 刷新所有已注册控件，
    # 控件销毁后注册表残留悬空条目可致原生崩溃；直接写 qconfig.theme 字段
    # 即可让之后构造的控件按深色配色（应用无动态换肤需求）。
    qconfig.theme = Theme.DARK
    application.setWindowIcon(load_app_icon())


def create_application(arguments: Sequence[str] | None = None) -> QApplication:
    existing = QApplication.instance()
    if existing is not None:
        return existing

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    application = QApplication(list(arguments) if arguments is not None else sys.argv)
    application.setApplicationName("SiteTask AI")
    application.setOrganizationName("SiteTaskAI")
    application.setQuitOnLastWindowClosed(True)
    configure_application_style(application)
    return application


def run(arguments: Sequence[str] | None = None) -> int:
    logger = configure_logging()
    install_global_exception_handler(logger)
    logger.info("Application starting")
    application = create_application(arguments)
    window = MainWidget()
    tray = TrayIcon()
    notification_service = NotificationService(window.repository)
    notification_timer = QTimer(application)
    notification_timer.setObjectName("notificationTimer")
    notification_timer.setInterval(60_000)

    def check_notifications() -> None:
        try:
            notification_service.check_due_tasks(
                window.settings.notifications,
                paused=window.notifications_paused,
            )
        except Exception:
            # Notification failures must never stop manual task management.
            logger.warning("Notification check failed", exc_info=True)
            return

    notification_timer.timeout.connect(check_notifications)
    notification_timer.start()
    QTimer.singleShot(0, check_notifications)
    tray_available = QSystemTrayIcon.isSystemTrayAvailable()
    application.setQuitOnLastWindowClosed(not tray_available)
    window.set_tray_available(tray_available)

    tray.open_widget_requested.connect(window.show_from_tray)
    tray.add_task_requested.connect(lambda: _show_then(window, window.open_task_editor))
    tray.ai_task_requested.connect(window.focus_natural_input)
    tray.all_tasks_requested.connect(lambda: _show_then(window, window.open_all_tasks))
    tray.toggle_pin_requested.connect(lambda: window.set_pinned(not window.is_pinned))
    tray.notifications_paused.connect(window.set_notifications_paused)
    tray.settings_requested.connect(lambda: _show_then(window, window.open_settings))
    tray.toggle_widget_requested.connect(window.toggle_from_tray)
    tray.exit_requested.connect(lambda: _exit_from_tray(tray, window))

    if tray_available:
        tray.show()
    window.show()
    exit_code = application.exec()
    tray.hide()
    logger.info("Application stopped with exit code %s", exit_code)
    return exit_code


def _show_then(window: MainWidget, action: Callable[[], None]) -> None:
    window.show_from_tray()
    action()


def _exit_from_tray(tray: TrayIcon, window: MainWidget) -> None:
    tray.hide()
    window.exit_application()
