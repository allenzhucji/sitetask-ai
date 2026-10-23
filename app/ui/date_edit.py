from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QTextCharFormat
from PySide6.QtWidgets import QCalendarWidget, QDateEdit, QToolButton

from app.ui.icon_factory import make_flat_icon


class StyledDateEdit(QDateEdit):
    """Date editor with the shared SiteTask calendar presentation."""

    CALENDAR_MINIMUM_WIDTH = 292
    CALENDAR_MINIMUM_HEIGHT = 248

    def __init__(self) -> None:
        super().__init__()
        self.setCalendarPopup(True)
        self.setDisplayFormat("yyyy-MM-dd")

        calendar = self.calendarWidget()
        calendar.setObjectName("taskCalendar")
        calendar.setMinimumSize(
            self.CALENDAR_MINIMUM_WIDTH,
            self.CALENDAR_MINIMUM_HEIGHT,
        )
        calendar.setGridVisible(False)
        calendar.setNavigationBarVisible(True)
        calendar.setVerticalHeaderFormat(
            QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader
        )
        calendar.setHorizontalHeaderFormat(
            QCalendarWidget.HorizontalHeaderFormat.ShortDayNames
        )

        header_format = QTextCharFormat()
        header_format.setForeground(QColor("#9099a8"))
        header_format.setBackground(QColor("#252a34"))
        header_format.setFontWeight(600)
        calendar.setHeaderTextFormat(header_format)

        previous_button = calendar.findChild(QToolButton, "qt_calendar_prevmonth")
        next_button = calendar.findChild(QToolButton, "qt_calendar_nextmonth")
        if previous_button is not None:
            previous_button.setIcon(make_flat_icon("chevron_left"))
            previous_button.setIconSize(QSize(16, 16))
        if next_button is not None:
            next_button.setIcon(make_flat_icon("chevron_right"))
            next_button.setIconSize(QSize(16, 16))

        weekday_format = QTextCharFormat()
        weekday_format.setForeground(QColor("#d9dee7"))
        weekend_format = QTextCharFormat()
        weekend_format.setForeground(QColor("#d58a8f"))
        for day in (
            Qt.DayOfWeek.Monday,
            Qt.DayOfWeek.Tuesday,
            Qt.DayOfWeek.Wednesday,
            Qt.DayOfWeek.Thursday,
            Qt.DayOfWeek.Friday,
        ):
            calendar.setWeekdayTextFormat(day, weekday_format)
        for day in (Qt.DayOfWeek.Saturday, Qt.DayOfWeek.Sunday):
            calendar.setWeekdayTextFormat(day, weekend_format)
