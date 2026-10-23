from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCalendarWidget, QToolButton

from app.application import load_application_stylesheet
from app.ui.date_combo import DateComboBox
from app.ui.date_edit import StyledDateEdit
from app.ui.quick_add_widget import QuickAddWidget
from app.ui.task_editor_dialog import TaskEditorDialog


def test_styled_date_edit_configures_spacious_consistent_calendar(qtbot):
    date_edit = StyledDateEdit()
    qtbot.addWidget(date_edit)
    calendar = date_edit.calendarWidget()

    assert date_edit.calendarPopup()
    assert date_edit.displayFormat() == "yyyy-MM-dd"
    assert calendar.objectName() == "taskCalendar"
    assert calendar.minimumWidth() == StyledDateEdit.CALENDAR_MINIMUM_WIDTH
    assert calendar.minimumHeight() == StyledDateEdit.CALENDAR_MINIMUM_HEIGHT
    assert not calendar.isGridVisible()
    assert (
        calendar.verticalHeaderFormat()
        == QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader
    )
    assert (
        calendar.horizontalHeaderFormat()
        == QCalendarWidget.HorizontalHeaderFormat.ShortDayNames
    )
    assert (
        calendar.weekdayTextFormat(Qt.DayOfWeek.Monday).foreground().color().name()
        == "#d9dee7"
    )
    assert (
        calendar.weekdayTextFormat(Qt.DayOfWeek.Sunday).foreground().color().name()
        == "#d58a8f"
    )
    assert calendar.headerTextFormat().background().color().name() == "#252a34"
    previous = calendar.findChild(QToolButton, "qt_calendar_prevmonth")
    following = calendar.findChild(QToolButton, "qt_calendar_nextmonth")
    assert previous is not None and not previous.icon().isNull()
    assert following is not None and not following.icon().isNull()


def test_task_entry_surfaces_share_the_styled_date_edit(qtbot):
    quick_add = QuickAddWidget()
    editor = TaskEditorDialog()
    qtbot.addWidget(quick_add)
    qtbot.addWidget(editor)

    # quick add 用滚动日期列表（DateComboBox），编辑器仍用日历弹窗
    assert isinstance(quick_add.date_input, DateComboBox)
    assert isinstance(editor.due_date_input, StyledDateEdit)


def test_dark_theme_contains_calendar_and_date_font_styles():
    stylesheet = load_application_stylesheet()

    assert "QDateEdit" in stylesheet
    assert "QCalendarWidget QWidget#qt_calendar_navigationbar" in stylesheet
    assert "QCalendarWidget QToolButton:hover" in stylesheet
    assert "QCalendarWidget QAbstractItemView:item:hover" in stylesheet
    # Win11 优先 Segoe UI Variable，回退链保持旧字体（Win10 下同样可用）
    assert 'font-family: "Segoe UI Variable Text", "Segoe UI", "Microsoft YaHei UI"' in stylesheet
