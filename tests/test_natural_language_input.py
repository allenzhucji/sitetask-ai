from __future__ import annotations

from datetime import date, datetime

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication

from app.database.connection import Database
from app.database.task_repository import TaskRepository
from app.models.task import Category, TaskSource
from app.models.parsed_task import ParsedTaskResult
from app.models.settings import AISettings
from app.services.settings_service import SettingsService
from app.ui.main_widget import MainWidget
from app.ui.task_preview_dialog import TaskPreviewDialog
from app.utils.paths import AppPaths


TODAY = date(2026, 7, 17)
NOW = datetime.fromisoformat("2026-07-17T09:30:00+04:00")


def make_widget(qtbot, tmp_path, *, credential_service=None, ai_parser=None):
    paths = AppPaths(tmp_path)
    repository = TaskRepository(Database(paths.database_file), clock=lambda: NOW)
    widget = MainWidget(
        SettingsService(paths),
        repository,
        today_provider=lambda: TODAY,
        now_provider=lambda: NOW,
        credential_service=credential_service,
        ai_parser=ai_parser,
    )
    qtbot.addWidget(widget)
    widget.show()
    return widget, repository


def test_far_future_parse_is_previewed_before_saving(qtbot, tmp_path):
    widget, repository = make_widget(qtbot, tmp_path)
    widget.ai_input.text_input.setText("下个月15号提交月度报告")

    def confirm_preview() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, TaskPreviewDialog)
        assert repository.list_all_tasks() == []
        assert dialog.title_input.text() == "提交月度报告"
        assert dialog.due_date_input.text() == "2026-08-15"
        assert Category(dialog.category_input.currentData()) is Category.REPORT
        dialog.confirm_button.click()

    QTimer.singleShot(0, confirm_preview)
    qtbot.mouseClick(widget.ai_input.parse_button, Qt.MouseButton.LeftButton)

    tasks = repository.list_all_tasks()
    assert len(tasks) == 1
    assert tasks[0].due_date == date(2026, 8, 15)
    assert tasks[0].source is TaskSource.LOCAL_PARSER
    assert widget.sections == []
    assert repository.count_later_tasks(TODAY) == 1
    assert widget.ai_input.text_input.text() == ""
    assert widget.ai_input.status_label.text() == (
        "任务已保存，将在进入未来三天范围后显示。"
    )


def test_missing_date_can_be_completed_manually_in_preview(qtbot, tmp_path):
    widget, repository = make_widget(qtbot, tmp_path)
    widget.ai_input.text_input.setText("回复 EFI-012")

    def edit_preview() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, TaskPreviewDialog)
        assert not dialog.confirm_button.isEnabled()
        assert not dialog.due_date_input.isReadOnly()
        dialog.due_date_input.setText("2026-07-18")
        assert dialog.confirm_button.isEnabled()
        dialog.confirm_button.click()

    QTimer.singleShot(0, edit_preview)
    qtbot.mouseClick(widget.ai_input.parse_button, Qt.MouseButton.LeftButton)

    task = repository.list_all_tasks()[0]
    assert task.title == "回复 EFI-012"
    assert task.due_date == date(2026, 7, 18)
    assert task.category is Category.EFI
    assert [section.title for section in widget.sections] == ["TOMORROW"]


def test_cancel_keeps_original_input_and_does_not_save(qtbot, tmp_path):
    widget, repository = make_widget(qtbot, tmp_path)
    original = "明天下午3点回复IRF-023"
    widget.ai_input.text_input.setText(original)

    def cancel_preview() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, TaskPreviewDialog)
        dialog.cancel_button.click()

    QTimer.singleShot(0, cancel_preview)
    qtbot.mouseClick(widget.ai_input.parse_button, Qt.MouseButton.LeftButton)

    assert repository.list_all_tasks() == []
    assert widget.ai_input.text_input.text() == original


class FakeCredentials:
    def __init__(self, api_key="sk-test"):
        self.api_key = api_key

    def get_api_key(self):
        return self.api_key


class FakeAIParser:
    def __init__(self):
        self.calls = []

    def parse(self, text, **kwargs):
        self.calls.append((text, kwargs))
        return ParsedTaskResult(
            title="Renew the site access permit",
            due_date=date(2026, 10, 1),
            category=Category.FOLLOW_UP,
            confidence=0.94,
            parser_source="ai",
        )


def test_low_confidence_input_uses_ai_preview_and_saves_ai_source(qtbot, tmp_path):
    credentials = FakeCredentials()
    ai_parser = FakeAIParser()
    widget, repository = make_widget(
        qtbot,
        tmp_path,
        credential_service=credentials,
        ai_parser=ai_parser,
    )
    widget.settings.ai = AISettings(
        enabled=True,
        model="test-model",
        local_parser_threshold=1.0,
    )
    original = "On 1 October renew the site access permit"
    widget.ai_input.text_input.setText(original)

    def confirm_preview() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, TaskPreviewDialog)
        assert dialog.source_label.text() == "AI"
        assert dialog.due_date_input.text() == "2026-10-01"
        assert repository.list_all_tasks() == []
        dialog.confirm_button.click()

    QTimer.singleShot(0, confirm_preview)
    qtbot.mouseClick(widget.ai_input.parse_button, Qt.MouseButton.LeftButton)

    task = repository.list_all_tasks()[0]
    assert task.source is TaskSource.AI
    assert task.due_date == date(2026, 10, 1)
    assert repository.count_later_tasks(TODAY) == 1
    assert ai_parser.calls[0][0] == original


def test_ai_enabled_without_key_shows_confirmation_warning(qtbot, tmp_path):
    widget, repository = make_widget(
        qtbot,
        tmp_path,
        credential_service=FakeCredentials(None),
        ai_parser=FakeAIParser(),
    )
    widget.settings.ai = AISettings(
        enabled=True,
        model="test-model",
        local_parser_threshold=1.0,
    )
    original = "回复 EFI-012"
    widget.ai_input.text_input.setText(original)

    def inspect_and_cancel_preview() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, TaskPreviewDialog)
        assert dialog.source_label.text() == "Local parser"
        assert "no API key is configured" in dialog.warning_label.text()
        assert not dialog.due_date_input.isReadOnly()
        dialog.cancel_button.click()

    QTimer.singleShot(0, inspect_and_cancel_preview)
    qtbot.mouseClick(widget.ai_input.parse_button, Qt.MouseButton.LeftButton)

    assert repository.list_all_tasks() == []
    assert widget.ai_input.text_input.text() == original
