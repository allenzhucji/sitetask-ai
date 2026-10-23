from __future__ import annotations

from datetime import date, datetime

from PySide6.QtCore import QMimeData, QPointF

from app.database.connection import Database
from app.database.task_repository import TaskRepository
from app.models.task import Priority, Task
from app.services.settings_service import SettingsService
from app.ui.main_widget import MainWidget
from app.ui.task_item import TaskItem
from app.ui.task_section import TaskSection
from app.utils.paths import AppPaths


TODAY = date(2026, 7, 17)
FIXED_NOW = datetime.fromisoformat("2026-07-17T08:00:00+04:00")


def add_task(
    repository: TaskRepository,
    title: str,
    due_date: date,
    *,
    priority: Priority = Priority.NORMAL,
) -> Task:
    return repository.create_task(
        Task(
            title=title,
            due_date=due_date,
            priority=priority,
            created_at=FIXED_NOW,
            updated_at=FIXED_NOW,
        )
    )


class FakeDropEvent:
    def __init__(self, task_id: int, y: float) -> None:
        self._mime_data = QMimeData()
        self._mime_data.setData(
            TaskItem.TASK_ID_MIME_TYPE,
            str(task_id).encode("ascii"),
        )
        self._position = QPointF(0, y)
        self.accepted = False
        self.ignored = False

    def mimeData(self) -> QMimeData:
        return self._mime_data

    def position(self) -> QPointF:
        return self._position

    def acceptProposedAction(self) -> None:
        self.accepted = True

    def ignore(self) -> None:
        self.ignored = True


def make_widget(tmp_path) -> tuple[MainWidget, TaskRepository, dict[str, Task]]:
    paths = AppPaths(tmp_path)
    repository = TaskRepository(Database(paths.database_file), clock=lambda: FIXED_NOW)
    tasks = {
        "overdue": add_task(repository, "Overdue", date(2026, 7, 16)),
        "today_normal": add_task(repository, "Today normal", TODAY),
        "today_low": add_task(
            repository,
            "Today low",
            TODAY,
            priority=Priority.LOW,
        ),
        "tomorrow": add_task(
            repository,
            "Tomorrow low",
            date(2026, 7, 18),
            priority=Priority.LOW,
        ),
        "day_after": add_task(repository, "Day after", date(2026, 7, 19)),
        "later": add_task(repository, "Later", date(2026, 7, 20)),
    }
    widget = MainWidget(
        SettingsService(paths),
        repository,
        today_provider=lambda: TODAY,
    )
    return widget, repository, tasks


def test_all_visible_items_drag_and_all_sections_accept_drops(qtbot, tmp_path):
    widget, _, _ = make_widget(tmp_path)
    qtbot.addWidget(widget)
    widget.show()

    sections = {section.title: section for section in widget.sections}

    assert sections["NO DUE"].task_items[0].draggable
    assert sections["NO DUE"].accepts_drops
    for title in ("TODAY", "TOMORROW", "DAY AFTER TOMORROW"):
        assert sections[title].accepts_drops
        assert all(item.draggable for item in sections[title].task_items)


def test_drop_to_today_first_emits_order_and_urgent_request(qtbot, tmp_path):
    widget, _, tasks = make_widget(tmp_path)
    qtbot.addWidget(widget)
    widget.show()
    today_section = next(section for section in widget.sections if section.title == "TODAY")
    emitted: list[tuple[int, date, list[int], bool]] = []
    today_section.move_requested.connect(
        lambda task_id, due_date, task_ids, urgent: emitted.append(
            (task_id, due_date, task_ids, urgent)
        )
    )

    event = FakeDropEvent(tasks["today_low"].id, 0)
    today_section.dropEvent(event)

    assert event.accepted
    assert emitted == [
        (
            tasks["today_low"].id,
            TODAY,
            [tasks["today_low"].id, tasks["today_normal"].id],
            True,
        )
    ]


def test_tomorrow_drop_never_requests_urgent(qtbot):
    tasks = [
        Task(id=1, title="First", due_date=date(2026, 7, 18)),
        Task(id=2, title="Second", due_date=date(2026, 7, 18)),
    ]
    section = TaskSection(
        "TOMORROW",
        tasks,
        TODAY,
        due_date=date(2026, 7, 18),
        items_draggable=True,
        accepts_drops=True,
    )
    qtbot.addWidget(section)
    section.show()
    emitted: list[tuple[int, date, list[int], bool]] = []
    section.move_requested.connect(
        lambda task_id, due_date, task_ids, urgent: emitted.append(
            (task_id, due_date, task_ids, urgent)
        )
    )

    section.dropEvent(FakeDropEvent(2, 0))

    assert emitted == [(2, date(2026, 7, 18), [2, 1], False)]


def test_main_widget_persists_today_order_and_sets_first_urgent(qtbot, tmp_path):
    widget, repository, tasks = make_widget(tmp_path)
    qtbot.addWidget(widget)

    widget._move_task(
        tasks["today_low"].id,
        TODAY,
        [tasks["today_low"].id, tasks["today_normal"].id],
        True,
    )

    qtbot.waitUntil(
        lambda: next(
            section for section in widget.sections if section.title == "TODAY"
        ).task_items[0].task.id
        == tasks["today_low"].id
    )

    today_section = next(section for section in widget.sections if section.title == "TODAY")
    assert [item.task.id for item in today_section.task_items] == [
        tasks["today_low"].id,
        tasks["today_normal"].id,
    ]
    assert repository.get_task(tasks["today_low"].id).priority is Priority.URGENT
    assert repository.get_task(tasks["today_low"].id).due_date == TODAY


def test_main_widget_does_not_set_tomorrow_task_urgent(qtbot, tmp_path):
    widget, repository, tasks = make_widget(tmp_path)
    qtbot.addWidget(widget)

    widget._move_task(
        tasks["tomorrow"].id,
        date(2026, 7, 18),
        [tasks["tomorrow"].id],
        True,
    )

    assert repository.get_task(tasks["tomorrow"].id).priority is Priority.LOW


def test_reorder_calculation_inserts_cross_date_task(qtbot):
    section = TaskSection(
        "TODAY",
        [Task(id=1, title="Only", due_date=TODAY)],
        TODAY,
        due_date=TODAY,
        items_draggable=True,
        accepts_drops=True,
    )
    qtbot.addWidget(section)

    assert section.ordered_task_ids_for_drop(999, 0) == [999, 1]


def test_cross_date_drop_emits_target_date_and_insertion_order(qtbot, tmp_path):
    widget, _, tasks = make_widget(tmp_path)
    qtbot.addWidget(widget)
    widget.show()
    tomorrow = next(section for section in widget.sections if section.title == "TOMORROW")
    emitted: list[tuple[int, date, list[int], bool]] = []
    tomorrow.move_requested.connect(
        lambda task_id, due_date, task_ids, urgent: emitted.append(
            (task_id, due_date, task_ids, urgent)
        )
    )

    event = FakeDropEvent(tasks["overdue"].id, 0)
    tomorrow.dropEvent(event)

    assert event.accepted
    assert emitted == [
        (
            tasks["overdue"].id,
            date(2026, 7, 18),
            [tasks["overdue"].id, tasks["tomorrow"].id],
            False,
        )
    ]


def test_empty_date_target_appears_during_drag_and_accepts_drop(qtbot, tmp_path):
    paths = AppPaths(tmp_path)
    repository = TaskRepository(Database(paths.database_file), clock=lambda: FIXED_NOW)
    task = add_task(repository, "Move me", TODAY)
    widget = MainWidget(
        SettingsService(paths),
        repository,
        today_provider=lambda: TODAY,
    )
    qtbot.addWidget(widget)
    widget.show()
    tomorrow = next(
        section
        for section in widget.empty_drop_targets
        if section.title == "TOMORROW"
    )
    assert tomorrow.isHidden()

    widget._set_empty_drop_targets_visible(True)
    assert tomorrow.isVisible()
    event = FakeDropEvent(task.id, 0)
    tomorrow.dragMoveEvent(event)

    assert event.accepted
    assert tomorrow.drop_indicator.isVisible()


def test_main_widget_cross_date_move_preserves_task_and_refreshes(qtbot, tmp_path):
    widget, repository, tasks = make_widget(tmp_path)
    qtbot.addWidget(widget)

    widget._move_task(
        tasks["today_low"].id,
        date(2026, 7, 18),
        [tasks["today_low"].id, tasks["tomorrow"].id],
        False,
    )

    qtbot.waitUntil(
        lambda: repository.get_task(tasks["today_low"].id).due_date
        == date(2026, 7, 18)
    )
    moved = repository.get_task(tasks["today_low"].id)
    assert moved is not None
    assert moved.priority is Priority.LOW
    assert moved.due_date == date(2026, 7, 18)
    assert not moved.no_due


def test_drag_to_no_due_sets_long_term_state_and_clears_time(qtbot, tmp_path):
    widget, repository, tasks = make_widget(tmp_path)
    qtbot.addWidget(widget)
    timed = repository.get_task(tasks["tomorrow"].id).model_copy(
        update={"due_time": datetime.strptime("10:30", "%H:%M").time()}
    )
    repository.update_task(timed)
    widget.refresh_tasks()
    no_due = next(section for section in widget.sections if section.title == "NO DUE")
    target_ids = [tasks["tomorrow"].id] + [
        item.task.id for item in no_due.task_items
    ]

    widget._move_task(tasks["tomorrow"].id, None, target_ids, False)
    qtbot.waitUntil(
        lambda: repository.get_task(tasks["tomorrow"].id).no_due
        and any(
            item.task.id == tasks["tomorrow"].id
            for section in widget.sections
            if section.title == "NO DUE"
            for item in section.task_items
        )
    )

    moved = repository.get_task(tasks["tomorrow"].id)
    assert moved.no_due
    assert moved.due_time is None
    assert moved.id in {
        item.task.id
        for section in widget.sections
        if section.title == "NO DUE"
        for item in section.task_items
    }


def test_drag_from_no_due_assigns_target_date(qtbot, tmp_path):
    widget, repository, tasks = make_widget(tmp_path)
    qtbot.addWidget(widget)
    widget._move_task(
        tasks["overdue"].id,
        None,
        [tasks["overdue"].id],
        False,
    )
    qtbot.waitUntil(lambda: repository.get_task(tasks["overdue"].id).no_due)

    widget._move_task(
        tasks["overdue"].id,
        date(2026, 7, 18),
        [tasks["overdue"].id, tasks["tomorrow"].id],
        False,
    )
    qtbot.waitUntil(
        lambda: repository.get_task(tasks["overdue"].id).due_date
        == date(2026, 7, 18)
        and not repository.get_task(tasks["overdue"].id).no_due
    )
