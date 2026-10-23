from __future__ import annotations

from datetime import date, datetime

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QApplication,
    QDialogButtonBox,
    QInputDialog,
    QMessageBox,
)

from app.database.connection import Database
from app.database.task_repository import TaskRepository
from app.models.task import Task, TaskStatus
from app.services.settings_service import SettingsService
from app.ui.main_widget import MainWidget
from app.ui.task_editor_dialog import TaskEditorDialog
from app.utils.paths import AppPaths


TODAY = date(2026, 7, 17)
FIXED_NOW = datetime.fromisoformat("2026-07-17T08:00:00+04:00")


def make_widget(tmp_path) -> tuple[MainWidget, TaskRepository, Task]:
    paths = AppPaths(tmp_path)
    repository = TaskRepository(Database(paths.database_file), clock=lambda: FIXED_NOW)
    task = repository.create_task(
        Task(
            title="Reply IRF-023",
            due_date=TODAY,
            created_at=FIXED_NOW,
            updated_at=FIXED_NOW,
        )
    )
    widget = MainWidget(
        SettingsService(paths),
        repository,
        today_provider=lambda: TODAY,
    )
    return widget, repository, task


def test_complete_marks_card_and_undo_restores_task(qtbot, tmp_path):
    widget, repository, task = make_widget(tmp_path)
    qtbot.addWidget(widget)
    widget.show()
    task_item = widget.sections[0].task_items[0]
    assert widget.summary_label.text() == "Next 3 Days：1\nAfter 3 Days：0"

    qtbot.mouseClick(task_item.complete_checkbox, Qt.MouseButton.LeftButton)

    completed = repository.get_task(task.id)
    assert completed is not None
    assert completed.status is TaskStatus.COMPLETED
    assert task_item.title_label.font().strikeOut()
    assert not task_item.complete_checkbox.isEnabled()
    assert widget.completion_refresh_timer.interval() == 2_000
    assert widget.completion_refresh_timer.isActive()
    assert widget.toast.isVisible()
    # Count refreshes immediately while the completed card remains visible
    # for the two-second Undo window.
    assert widget.summary_label.text() == "Next 3 Days：0\nAfter 3 Days：0"

    qtbot.mouseClick(widget.toast.undo_button, Qt.MouseButton.LeftButton)

    restored = repository.get_task(task.id)
    assert restored is not None
    assert restored.status is TaskStatus.PENDING
    assert widget.last_completed_task_id is None
    assert [section.title for section in widget.sections] == ["TODAY"]
    assert widget.summary_label.text() == "Next 3 Days：1\nAfter 3 Days：0"


def test_completion_timer_removes_card_after_delay(qtbot, tmp_path):
    widget, repository, task = make_widget(tmp_path)
    qtbot.addWidget(widget)
    widget.show()
    task_item = widget.sections[0].task_items[0]

    qtbot.mouseClick(task_item.complete_checkbox, Qt.MouseButton.LeftButton)
    qtbot.wait(2_100)

    assert widget.sections == []
    assert repository.get_task(task.id).status is TaskStatus.COMPLETED
    assert widget.empty_state is not None


def test_context_menu_and_edit_duplicate_change_date_delete(
    qtbot,
    tmp_path,
    monkeypatch,
):
    widget, repository, task = make_widget(tmp_path)
    qtbot.addWidget(widget)
    task_item = widget.sections[0].task_items[0]

    assert [action.text() for action in task_item.build_context_menu().actions()] == [
        "Edit",
        "Mark Completed",
        "Change Due Date",
        "Duplicate",
        "Delete",
    ]

    def update_title() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, TaskEditorDialog)
        dialog.title_input.setText("Updated IRF")
        dialog.button_box.button(QDialogButtonBox.StandardButton.Save).click()

    QTimer.singleShot(0, update_title)
    widget._edit_task(task.id)
    assert repository.get_task(task.id).title == "Updated IRF"

    widget._duplicate_task(task.id)
    duplicates = repository.search_tasks("Updated IRF")
    assert len(duplicates) == 2
    assert any(duplicate.title == "Updated IRF (Copy)" for duplicate in duplicates)

    monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: ("2026-08-15", True))
    widget._change_due_date(task.id)
    assert repository.get_task(task.id).due_date == date(2026, 8, 15)
    assert task.id not in {
        item.task.id for section in widget.sections for item in section.task_items
    }

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    widget._delete_task(task.id)
    assert repository.get_task(task.id) is None


def test_double_click_task_opens_editor(qtbot, tmp_path):
    widget, repository, task = make_widget(tmp_path)
    qtbot.addWidget(widget)
    widget.show()
    task_item = widget.sections[0].task_items[0]

    def update_title() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, TaskEditorDialog)
        dialog.title_input.setText("Edited by double click")
        dialog.button_box.button(QDialogButtonBox.StandardButton.Save).click()

    QTimer.singleShot(0, update_title)
    qtbot.mouseDClick(task_item, Qt.MouseButton.LeftButton)

    assert repository.get_task(task.id).title == "Edited by double click"
