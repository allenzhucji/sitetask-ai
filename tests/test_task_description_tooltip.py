from datetime import date, datetime

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, QTimer, Qt
from PySide6.QtGui import QCursor, QHelpEvent, QMouseEvent, QTextCursor, QTextDocument
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QToolTip

from app.database.connection import Database
from app.database.task_repository import TaskRepository
from app.models.task import Task
from app.services.settings_service import SettingsService
from app.ui.main_widget import MainWidget
from app.ui.task_editor_dialog import TaskEditorDialog
from app.ui.task_item import TaskItem
from app.utils.paths import AppPaths

TODAY = date(2026, 10, 3)
NOW = datetime.fromisoformat("2026-10-03T08:00:00+04:00")


def plain(tooltip):
    doc = QTextDocument()
    doc.setHtml(tooltip)
    return doc.toPlainText().replace("\u200b", "").strip()


@pytest.mark.parametrize("no_due", [False, True])
def test_hover_card_and_title_show_complete_safe_description(qtbot, no_due):
    description = '下一步：核实 A&B\n<img src="file:///not-an-image.png">\n' + "https://example.test/" + "a" * 180
    item = TaskItem(Task(id=1, title="Follow up", due_date=TODAY, no_due=no_due, description=description), TODAY)
    qtbot.addWidget(item)
    item.resize(400, 60)
    item.show()
    for target in (item, item.title_label, item.metadata_label, item.priority_dot):
        assert plain(target.toolTip()) == description
        assert "<img " not in target.toolTip()
    assert item.complete_checkbox.toolTip() == "Mark completed"
    for target in (item, item.title_label):
        local = QPoint(4, 4)
        event = QHelpEvent(QEvent.Type.ToolTip, local, target.mapToGlobal(local))
        QApplication.sendEvent(target, event)
        popup = item.description_popup
        qtbot.waitUntil(popup.isVisible)
        assert popup.text_edit.toPlainText() == description
        assert popup.width() <= 500  # Includes the long unbroken URL, not screen-wide.
        assert popup.height() > item.fontMetrics().height() * 3
        popup.hide()


@pytest.mark.parametrize("description", [None, "", " \n\t "])
def test_empty_description_has_no_card_tooltip(qtbot, description):
    item = TaskItem(Task(title="No description", due_date=TODAY, description=description), TODAY)
    qtbot.addWidget(item)
    for target in (item, item.title_label, item.metadata_label, item.priority_dot):
        assert target.toolTip() == ""


def test_new_edit_clear_and_timer_refresh_update_card_and_all_tasks(qtbot, tmp_path):
    paths = AppPaths(tmp_path)
    repo = TaskRepository(Database(paths.database_file), clock=lambda: NOW)
    widget = MainWidget(SettingsService(paths), repo, today_provider=lambda: TODAY)
    qtbot.addWidget(widget)
    assert widget.testAttribute(Qt.WidgetAttribute.WA_AlwaysShowToolTips)

    def save_new():
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, TaskEditorDialog)
        dialog.title_input.setText("New task")
        dialog.description_input.setPlainText("Original description")
        dialog.button_box.button(QDialogButtonBox.StandardButton.Save).click()

    QTimer.singleShot(0, save_new)
    widget.open_task_editor()
    task = repo.list_all_tasks()[0]

    def card():
        return next(i for section in widget.sections for i in section.task_items if i.task.id == task.id)

    assert plain(card().title_label.toolTip()) == "Original description"
    widget.open_all_tasks()
    table = widget.all_tasks_dialog
    table.set_filter("All")
    assert table.testAttribute(Qt.WidgetAttribute.WA_AlwaysShowToolTips)
    assert plain(table.table.item(0, 0).toolTip()) == "Original description"

    for description in ("Edited description\nSecond line & <literal>", ""):
        def save_edit():
            dialog = QApplication.activeModalWidget()
            assert isinstance(dialog, TaskEditorDialog)
            dialog.description_input.setPlainText(description)
            dialog.button_box.button(QDialogButtonBox.StandardButton.Save).click()
        QTimer.singleShot(0, save_edit)
        widget.open_task_editor(task.id)
        assert plain(card().toolTip()) == description
        assert plain(card().title_label.toolTip()) == description
        for column in range(table.table.columnCount()):
            assert plain(table.table.item(0, column).toolTip()) == description

    current = repo.get_task(task.id)
    repo.update_task(current.model_copy(update={"description": "Refreshed from database"}))
    widget.refresh_timer.timeout.emit()
    assert plain(card().title_label.toolTip()) == "Refreshed from database"
    assert plain(table.table.item(0, 0).toolTip()) == "Refreshed from database"


def test_popup_allows_mouse_selection_and_exact_copy_and_survives_pointer_entry(qtbot):
    description = "first word & <literal>\nhttps://example.test/" + "abc" * 90
    item = TaskItem(Task(id=4, title="Copy details", due_date=TODAY, description=description), TODAY)
    qtbot.addWidget(item)
    item.resize(400, 60)
    item.show()
    local = QPoint(5, 5)
    QApplication.sendEvent(item.title_label, QHelpEvent(QEvent.Type.ToolTip, local, item.title_label.mapToGlobal(local)))
    popup = item.description_popup
    edit = popup.text_edit
    QCursor.setPos(edit.viewport().mapToGlobal(QPoint(10, 10)))
    qtbot.wait(900)
    assert popup.isVisible()
    assert edit.isReadOnly()
    press = QPoint(12, edit.fontMetrics().height() // 2 + 4)
    qtbot.mousePress(edit.viewport(), Qt.MouseButton.LeftButton, pos=press)
    qtbot.wait(550)
    qtbot.mouseRelease(edit.viewport(), Qt.MouseButton.LeftButton, pos=press)
    assert edit.textCursor().hasSelection()
    selected = edit.textCursor().selectedText()
    assert selected == "first"
    qtbot.keyClick(edit, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    assert QApplication.clipboard().text() == selected
    # Hold and drag selects an arbitrary range without any double-click.
    cursor = edit.textCursor()
    cursor.setPosition(0)
    start = edit.cursorRect(cursor).center()
    cursor.setPosition(10)
    end = edit.cursorRect(cursor).center()
    qtbot.mousePress(edit.viewport(), Qt.MouseButton.LeftButton, pos=start)
    QApplication.sendEvent(edit.viewport(), QMouseEvent(QEvent.Type.MouseMove, QPointF(end),
        QPointF(edit.viewport().mapToGlobal(end)), Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
    qtbot.mouseRelease(edit.viewport(), Qt.MouseButton.LeftButton, pos=end)
    assert edit.textCursor().selectedText() == "first word"
    qtbot.keyClick(edit, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    assert QApplication.clipboard().text() == "first word"
    qtbot.mouseClick(popup.copy_button, Qt.MouseButton.LeftButton)
    assert QApplication.clipboard().text() == description
    assert "\u200b" not in QApplication.clipboard().text()
    # Leaving both surfaces gives a short travel grace period, then dismisses.
    QCursor.setPos(popup.geometry().bottomRight() + QPoint(100, 100))
    qtbot.waitUntil(lambda: not popup.isVisible(), timeout=2000)


def test_visible_popup_keeps_selection_on_refresh_and_updates_or_hides_with_description(qtbot, tmp_path):
    paths = AppPaths(tmp_path)
    repo = TaskRepository(Database(paths.database_file), clock=lambda: NOW)
    task = repo.create_task(Task(title="Live description", due_date=TODAY, description="Keep this selection"))
    widget = MainWidget(SettingsService(paths), repo, today_provider=lambda: TODAY)
    qtbot.addWidget(widget)
    widget.show()
    card = widget.sections[0].task_items[0]
    local = QPoint(4, 4)
    QApplication.sendEvent(card, QHelpEvent(QEvent.Type.ToolTip, local, card.mapToGlobal(local)))
    popup = widget.description_popup
    popup.text_edit.selectAll()
    widget.refresh_tasks()
    assert popup.isVisible()
    assert popup.text_edit.textCursor().selectedText() == "Keep this selection"
    repo.update_task(repo.get_task(task.id).model_copy(update={"description": "New description"}))
    widget.refresh_tasks()
    assert popup.text_edit.toPlainText() == "New description"
    repo.update_task(repo.get_task(task.id).model_copy(update={"description": ""}))
    widget.refresh_tasks()
    assert not popup.isVisible()


def test_all_tasks_row_uses_selectable_popup_and_long_description_scrolls(qtbot, tmp_path):
    from app.ui.all_tasks_dialog import AllTasksDialog
    repo = TaskRepository(Database(tmp_path / "tasks.sqlite"), clock=lambda: NOW)
    description = "\n".join(f"Line {n}: long details" for n in range(150))
    repo.create_task(Task(title="Long details", due_date=TODAY, description=description))
    dialog = AllTasksDialog(repo, today_provider=lambda: TODAY)
    qtbot.addWidget(dialog)
    dialog.show()
    viewport = dialog.table.viewport()
    point = dialog.table.visualItemRect(dialog.table.item(0, 0)).center()
    QApplication.sendEvent(viewport, QHelpEvent(QEvent.Type.ToolTip, point, viewport.mapToGlobal(point)))
    popup = dialog.description_popup
    assert popup.isVisible()
    assert popup.text_edit.toPlainText() == description
    assert popup.height() <= 480
    qtbot.waitUntil(lambda: popup.text_edit.verticalScrollBar().maximum() > 0)
    qtbot.mouseClick(popup.close_button, Qt.MouseButton.LeftButton)
    assert not popup.isVisible()


def test_header_buttons_align_and_sources_are_compact_but_copy_keeps_full_text(qtbot):
    body = "跟进：等待顾问回复。\n时间：申请10月5日09:00，尚待确认。\n备注：Example User无需到场。"
    url = "https://mail.google.com/mail/u/?authuser=example%40gmail.com#all/123"
    description = body + "\n\n来源邮件：\n" + url
    item = TaskItem(Task(id=57, title="IRF103检查申请", due_date=TODAY, description=description), TODAY)
    qtbot.addWidget(item)
    item.resize(400, 60)
    item.show()
    p = QPoint(5, 5)
    QApplication.sendEvent(item, QHelpEvent(QEvent.Type.ToolTip, p, item.mapToGlobal(p)))
    popup = item.description_popup
    qtbot.waitUntil(popup.isVisible)
    assert popup.copy_button.height() == popup.close_button.height()
    assert popup.copy_button.geometry().top() == popup.close_button.geometry().top()
    assert popup.text_edit.toPlainText() == body
    assert popup.source_label.isVisible()
    assert "查看原邮件" in popup.source_label.text()
    qtbot.mouseClick(popup.copy_button, Qt.MouseButton.LeftButton)
    assert QApplication.clipboard().text() == description
