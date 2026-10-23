from __future__ import annotations

from datetime import date, datetime

from PySide6.QtCore import QDate

from app.database.connection import Database
from app.database.task_repository import TaskRepository
from app.services.settings_service import SettingsService
from app.ui.main_widget import MainWidget
from app.ui.quick_add_widget import QuickAddWidget
from app.utils.paths import AppPaths


TODAY = date(2026, 7, 17)
NEXT_DAY = date(2026, 7, 18)
FIXED_NOW = datetime.fromisoformat("2026-07-17T08:00:00+04:00")


class MutableToday:
    """A today_provider whose returned date can be advanced for rollover tests."""

    def __init__(self, value: date) -> None:
        self.value = value

    def __call__(self) -> date:
        return self.value


def make_widget(qtbot, tmp_path, today_provider):
    paths = AppPaths(tmp_path)
    repository = TaskRepository(Database(paths.database_file), clock=lambda: FIXED_NOW)
    widget = MainWidget(
        SettingsService(paths),
        repository,
        today_provider=today_provider,
        now_provider=lambda: FIXED_NOW,
    )
    qtbot.addWidget(widget)
    widget.show()
    return widget


def test_quick_add_advances_default_date_after_rollover(qtbot):
    today = MutableToday(TODAY)
    quick_add = QuickAddWidget(today_provider=today)
    qtbot.addWidget(quick_add)
    assert quick_add.date_input.date().toPython() == TODAY

    today.value = NEXT_DAY
    quick_add.refresh_date_if_auto()
    assert quick_add.date_input.date().toPython() == NEXT_DAY


def test_manually_chosen_date_is_not_overwritten(qtbot):
    today = MutableToday(TODAY)
    quick_add = QuickAddWidget(today_provider=today)
    qtbot.addWidget(quick_add)

    quick_add.date_input.setDate(QDate(2026, 7, 20))
    today.value = date(2026, 7, 19)
    quick_add.refresh_date_if_auto()
    assert quick_add.date_input.date().toPython() == date(2026, 7, 20)


def test_clear_inputs_resets_manual_choice_and_follows_today(qtbot):
    today = MutableToday(TODAY)
    quick_add = QuickAddWidget(today_provider=today)
    qtbot.addWidget(quick_add)

    quick_add.date_input.setDate(QDate(2026, 7, 20))
    quick_add.title_input.setText("Inspect reinforcement")
    quick_add.clear_inputs()
    assert quick_add.date_input.date().toPython() == TODAY

    today.value = NEXT_DAY
    quick_add.refresh_date_if_auto()
    assert quick_add.date_input.date().toPython() == NEXT_DAY


def test_widget_refresh_advances_quick_add_date_after_rollover(qtbot, tmp_path):
    today = MutableToday(TODAY)
    widget = make_widget(qtbot, tmp_path, today)
    assert widget.quick_add.date_input.date().toPython() == TODAY

    today.value = NEXT_DAY
    widget.refresh_tasks()
    assert widget.quick_add.date_input.date().toPython() == NEXT_DAY


def test_expanding_input_panel_advances_quick_add_date(qtbot, tmp_path):
    today = MutableToday(TODAY)
    widget = make_widget(qtbot, tmp_path, today)

    today.value = NEXT_DAY
    widget.set_input_panel_expanded(True)
    assert widget.quick_add.date_input.date().toPython() == NEXT_DAY
