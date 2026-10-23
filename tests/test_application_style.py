from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate, QSize
from PySide6.QtWidgets import QStyleFactory

from app.application import (
    STYLE_FILE,
    configure_application_style,
    load_application_stylesheet,
)
from app.services.settings_service import SettingsService
from app.ui.date_combo import DateComboBox
from app.ui.main_widget import MainWidget
from app.ui.title_bar import TitleBar
from app.utils.paths import AppPaths


def test_dark_stylesheet_resource_contains_main_and_dialog_styles():
    stylesheet = load_application_stylesheet()

    assert STYLE_FILE.is_file()
    # 主窗口背景由 MainWidget.paintEvent 绘制（Qt 顶层窗口不绘制 QSS 背景），
    # 此处断言对话框与面板样式仍由 QSS 控制
    assert "QDialog" in stylesheet
    assert "QWidget#titleBar" in stylesheet
    assert "QTableWidget" in stylesheet
    assert "QScrollBar:vertical" in stylesheet
    assert "QPushButton#pinButton:checked" in stylesheet
    assert "QLabel#previewWarning" in stylesheet
    assert "QFrame#toastWidget" in stylesheet
    toast_style = stylesheet.split("QFrame#toastWidget {", 1)[1].split("}", 1)[0]
    assert "border-radius: 8px;" in toast_style
    assert "QLabel#taskSummary" in stylesheet
    assert "padding: 0;" in stylesheet
    assert "@CHECK_ICON@" not in stylesheet
    assert "check.svg" in stylesheet
    assert (STYLE_FILE.parent.parent / "icons" / "check.svg").is_file()


def test_missing_stylesheet_is_recoverable(tmp_path):
    assert load_application_stylesheet(tmp_path / "missing.qss") == ""


def test_application_uses_fusion_and_global_dark_theme(qapp):
    configure_application_style(qapp)

    assert "Fusion" in QStyleFactory.keys()
    assert qapp.styleSheet() == load_application_stylesheet()


def test_quick_date_popup_is_limited_to_seven_centered_rows(qapp, qtbot):
    configure_application_style(qapp)
    combo = DateComboBox(today=date(2026, 8, 8))
    qtbot.addWidget(combo)
    combo.setObjectName("quickTaskDate")
    combo.setDate(QDate(2026, 8, 8))
    combo.resize(120, 44)
    combo.show()
    combo.showPopup()
    qapp.processEvents()

    view = combo.view()
    row_height = view.sizeHintForRow(combo.currentIndex())
    selected_rect = view.visualRect(view.currentIndex())

    assert view.viewport().height() <= row_height * DateComboBox.VISIBLE_ROWS
    assert (
        abs(selected_rect.center().y() - view.viewport().rect().center().y())
        <= row_height // 2
    )

    combo.hidePopup()


def test_title_bar_buttons_keep_real_18px_geometry_after_global_style(qapp, qtbot):
    configure_application_style(qapp)
    title_bar = TitleBar()
    qtbot.addWidget(title_bar)
    title_bar.resize(400, title_bar.height())
    title_bar.show()
    qapp.processEvents()

    buttons = (
        title_bar.pin_button,
        title_bar.all_tasks_button,
        title_bar.settings_button,
        title_bar.minimize_button,
        title_bar.close_button,
    )
    title_center = title_bar.title_label.geometry().center().y()

    assert {button.size() for button in buttons} == {QSize(18, 18)}
    assert all(button.geometry().bottom() < title_bar.height() for button in buttons)
    assert all(button.geometry().center().y() == title_center for button in buttons)


def test_main_widget_no_longer_owns_inline_theme(qtbot, tmp_path):
    widget = MainWidget(SettingsService(AppPaths(tmp_path)))
    qtbot.addWidget(widget)

    assert widget.styleSheet() == ""
