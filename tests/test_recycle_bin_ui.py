"""All Tasks recycle-bin page: read-only rows, restore, permanent delete with confirmation."""
from __future__ import annotations

from datetime import date, datetime

from PySide6.QtWidgets import QMessageBox

from app.database.connection import Database
from app.database.task_repository import TaskRepository
from app.models.task import Task
from app.services.settings_service import SettingsService
from app.ui.main_widget import MainWidget
from app.utils.paths import AppPaths

TODAY = date(2026, 10, 19)
NOW = datetime.fromisoformat('2026-10-19T09:00:00+04:00')


def make(qtbot, tmp_path):
    paths = AppPaths(tmp_path)
    repo = TaskRepository(Database(paths.database_file), clock=lambda: NOW)
    tasks = [repo.create_task(Task(title=f'Bin {i}', due_date=TODAY, created_at=NOW, updated_at=NOW)) for i in range(3)]
    widget = MainWidget(SettingsService(paths), repo, today_provider=lambda: TODAY, now_provider=lambda: NOW)
    qtbot.addWidget(widget)
    widget.show()
    widget.open_all_tasks()
    return widget, repo, widget.all_tasks_dialog, tasks


def test_recycle_bin_lists_deleted_tasks_read_only_and_restores(qtbot, tmp_path):
    widget, repo, dialog, tasks = make(qtbot, tmp_path)
    repo.soft_delete_task(tasks[0].id)
    dialog.set_filter('All')
    assert {t.id for t in dialog.current_tasks} == {tasks[1].id, tasks[2].id}
    dialog.set_filter('Recycle Bin')
    assert [t.id for t in dialog.current_tasks] == [tasks[0].id]
    assert dialog.empty_bin_button.isVisible() and dialog.empty_bin_button.isEnabled()
    dialog.select_task(tasks[0].id)
    assert not dialog.edit_button.isEnabled()
    assert dialog.status_button.text() == 'Restore' and dialog.delete_button.text() == 'Delete Permanently'
    dialog._emit_edit()  # double-click path: must not open an editor
    dialog.search_input.setText('Bin 0')
    assert [t.id for t in dialog.current_tasks] == [tasks[0].id]
    dialog.search_input.clear()
    dialog.select_task(tasks[0].id)
    dialog.status_button.click()
    assert repo.get_task(tasks[0].id) is not None
    assert dialog.current_tasks == []
    dialog.set_filter('All')
    assert not dialog.empty_bin_button.isVisible() and dialog.delete_button.text() == 'Delete'


def test_permanent_delete_requires_confirmation(qtbot, tmp_path, monkeypatch):
    widget, repo, dialog, tasks = make(qtbot, tmp_path)
    for task in tasks:
        repo.soft_delete_task(task.id)
    dialog.set_filter('Recycle Bin')
    dialog.select_task(tasks[0].id)
    monkeypatch.setattr(QMessageBox, 'warning', lambda *a, **k: QMessageBox.StandardButton.No)
    dialog.delete_button.click()
    assert len(repo.list_deleted_tasks()) == 3
    monkeypatch.setattr(QMessageBox, 'warning', lambda *a, **k: QMessageBox.StandardButton.Yes)
    dialog.select_task(tasks[0].id)
    dialog.delete_button.click()
    assert {t.id for t in repo.list_deleted_tasks()} == {tasks[1].id, tasks[2].id}
    dialog.empty_bin_button.click()
    assert repo.list_deleted_tasks() == []
    with repo.database.transaction() as connection:
        kinds = {r[0] for r in connection.execute('SELECT kind FROM task_tombstones')}
    assert kinds == {'purge'}


def test_existing_hard_delete_button_still_deletes_directly(qtbot, tmp_path, monkeypatch):
    widget, repo, dialog, tasks = make(qtbot, tmp_path)
    monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: QMessageBox.StandardButton.Yes)
    dialog.set_filter('All')
    dialog.select_task(tasks[1].id)
    dialog.delete_button.click()
    assert repo.get_task(tasks[1].id, include_deleted=True) is None
    assert repo.list_deleted_tasks() == []
    with repo.database.transaction() as connection:
        assert connection.execute('SELECT kind FROM task_tombstones').fetchone()[0] == 'hard_delete'
    assert widget.identity_check is not None
