from __future__ import annotations

from datetime import date, datetime

from PySide6.QtCore import QDate, QTimer, Qt
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QMessageBox

from app.database.connection import Database
from app.database.task_repository import TaskRepository
from app.models.task import Task, TaskStatus
from app.services.settings_service import SettingsService
from app.ui.all_tasks_dialog import AllTasksDialog
from app.ui.main_widget import MainWidget
from app.ui.task_editor_dialog import TaskEditorDialog
from app.utils.paths import AppPaths


TODAY = date(2026, 7, 17)
NOW = datetime.fromisoformat("2026-07-17T09:00:00+04:00")


def make_widget(qtbot, tmp_path):
    paths = AppPaths(tmp_path)
    repository = TaskRepository(Database(paths.database_file), clock=lambda: NOW)
    widget = MainWidget(
        SettingsService(paths),
        repository,
        today_provider=lambda: TODAY,
        now_provider=lambda: NOW,
    )
    qtbot.addWidget(widget)
    widget.show()
    widget.open_all_tasks()
    return widget, repository, widget.all_tasks_dialog


def test_search_is_combined_with_selected_filter(qtbot, tmp_path):
    widget, repository, dialog = make_widget(qtbot, tmp_path)
    repository.create_task(
        Task(
            title="Submit monthly report",
            description="August package",
            due_date=date(2026, 8, 15),
            created_at=NOW,
            updated_at=NOW,
        )
    )
    repository.create_task(
        Task(
            title="Review drawing",
            description="Report comments",
            due_date=TODAY,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    dialog.set_filter("Later")

    dialog.search_input.setText("report")

    assert [task.title for task in dialog.current_tasks] == ["Submit monthly report"]
    assert dialog.count_label.text() == "1 task"


def test_complete_and_restore_refresh_both_windows(qtbot, tmp_path):
    widget, repository, dialog = make_widget(qtbot, tmp_path)
    task = repository.create_task(
        Task(title="Reply EFI", due_date=TODAY, created_at=NOW, updated_at=NOW)
    )
    widget.refresh_tasks()
    dialog.set_filter("All")
    assert dialog.select_task(task.id)

    qtbot.mouseClick(dialog.status_button, Qt.MouseButton.LeftButton)
    assert repository.get_task(task.id).status is TaskStatus.COMPLETED
    assert widget.last_completed_task_id == task.id
    assert dialog.select_task(task.id)
    assert dialog.status_button.text() == "Restore"

    qtbot.mouseClick(dialog.status_button, Qt.MouseButton.LeftButton)
    assert repository.get_task(task.id).status is TaskStatus.PENDING
    assert widget.last_completed_task_id is None
    assert [section.title for section in widget.sections] == ["TODAY"]


def test_edit_can_move_task_to_later_and_delete_it(qtbot, tmp_path, monkeypatch):
    widget, repository, dialog = make_widget(qtbot, tmp_path)
    task = repository.create_task(
        Task(title="Inspect slab", due_date=TODAY, created_at=NOW, updated_at=NOW)
    )
    widget.refresh_tasks()
    dialog.set_filter("All")
    assert dialog.select_task(task.id)

    def edit_task() -> None:
        editor = QApplication.activeModalWidget()
        assert isinstance(editor, TaskEditorDialog)
        editor.title_input.setText("Inspect roof slab")
        editor.due_date_input.setDate(QDate(2026, 9, 1))
        editor.button_box.button(QDialogButtonBox.StandardButton.Save).click()

    QTimer.singleShot(0, edit_task)
    qtbot.mouseClick(dialog.edit_button, Qt.MouseButton.LeftButton)

    updated = repository.get_task(task.id)
    assert updated.title == "Inspect roof slab"
    assert updated.due_date == date(2026, 9, 1)
    assert widget.sections == []

    dialog.set_filter("Later")
    assert dialog.select_task(task.id)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    qtbot.mouseClick(dialog.delete_button, Qt.MouseButton.LeftButton)

    assert repository.get_task(task.id) is None
    assert dialog.table.rowCount() == 0
