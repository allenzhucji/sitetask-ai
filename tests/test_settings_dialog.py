from __future__ import annotations

from PySide6.QtCore import QTime, QTimer
from PySide6.QtWidgets import QApplication, QDialogButtonBox

from app.models.settings import Settings
from app.services.ai_task_parser import AIParseError
from app.services.settings_service import SettingsService
from app.ui.main_widget import MainWidget
from app.ui.settings_dialog import SettingsDialog
from app.utils.paths import AppPaths


class FakeCredentials:
    def __init__(self, api_key=None):
        self.api_key = api_key
        self.saved = []

    def masked_api_key(self):
        return "tes••••alue" if self.api_key else None

    def get_api_key(self):
        return self.api_key

    def save_api_key(self, api_key):
        self.saved.append(api_key)
        self.api_key = api_key
        return True


class FakeConnectionTester:
    def __init__(self, *, fails=False):
        self.fails = fails
        self.calls = []

    def test_connection(self, *, api_key, model):
        self.calls.append((api_key, model))
        if self.fails:
            raise AIParseError("OpenAI connection test failed.")


class FakeStartupService:
    def __init__(self, *, succeeds=True):
        self.succeeds = succeeds
        self.calls = []

    def apply(self, enabled):
        self.calls.append(enabled)
        return self.succeeds

    def enable(self):
        self.calls.append(True)
        return self.succeeds


def test_basic_and_ai_settings_are_editable(qtbot):
    credentials = FakeCredentials()
    dialog = SettingsDialog(
        Settings(),
        credential_service=credentials,
        connection_tester=FakeConnectionTester(),
    )
    qtbot.addWidget(dialog)

    dialog.close_to_tray_input.setChecked(False)
    dialog.show_overdue_input.setChecked(False)
    dialog.show_later_count_input.setChecked(False)
    dialog.apply_default_time_input.setChecked(True)
    dialog.default_due_time_input.setTime(QTime(16, 30))
    dialog.default_category_input.setCurrentText("Report")
    dialog.default_priority_input.setCurrentText("high")
    dialog.notifications_input.setChecked(False)
    dialog.startup_input.setChecked(True)
    dialog.ai_enabled_input.setChecked(True)
    dialog.api_key_input.setText("sk-new-test-value")
    dialog.model_input.setText(" structured-model ")
    dialog.local_threshold_input.setValue(0.85)
    updated = dialog.result_settings()

    assert not updated.window.close_to_tray
    assert not updated.display.show_overdue
    assert not updated.display.show_later_count
    assert updated.task_defaults.default_due_time == "16:30"
    assert updated.task_defaults.default_category == "Report"
    assert updated.task_defaults.default_priority == "high"
    assert not updated.notifications.enabled
    assert updated.ai.enabled is True
    assert updated.ai.model == "structured-model"
    assert updated.ai.local_parser_threshold == 0.85
    assert dialog.save_pending_api_key()
    assert credentials.saved == ["sk-new-test-value"]
    assert updated.startup.start_with_windows is True


def test_api_key_is_masked_and_connection_uses_typed_key(qtbot):
    credentials = FakeCredentials("test-stored-value")
    tester = FakeConnectionTester()
    dialog = SettingsDialog(
        Settings(),
        credential_service=credentials,
        connection_tester=tester,
    )
    qtbot.addWidget(dialog)

    assert dialog.api_key_input.text() == ""
    assert "tes••••alue" in dialog.api_key_input.placeholderText()
    dialog.api_key_input.setText("sk-unsaved-test-key")
    dialog.model_input.setText("test-model")
    dialog.test_connection_button.click()

    assert tester.calls == [("sk-unsaved-test-key", "test-model")]
    assert dialog.connection_status_label.text() == "Connection successful."


def test_connection_reports_missing_configuration_and_safe_failure(qtbot):
    credentials = FakeCredentials()
    tester = FakeConnectionTester(fails=True)
    dialog = SettingsDialog(
        Settings(),
        credential_service=credentials,
        connection_tester=tester,
    )
    qtbot.addWidget(dialog)

    dialog.test_connection_button.click()
    assert dialog.connection_status_label.text() == "API key is not configured."
    dialog.api_key_input.setText("sk-test")
    dialog.model_input.setText("test-model")
    dialog.test_connection_button.click()
    assert dialog.connection_status_label.text() == "OpenAI connection test failed."


def test_title_bar_settings_entry_saves_changes(qtbot, tmp_path):
    service = SettingsService(AppPaths(tmp_path))
    credentials = FakeCredentials()
    startup = FakeStartupService()
    widget = MainWidget(
        service,
        credential_service=credentials,
        startup_service=startup,
    )
    qtbot.addWidget(widget)
    widget.show()

    def save_settings() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, SettingsDialog)
        dialog.show_later_count_input.setChecked(False)
        dialog.ai_enabled_input.setChecked(True)
        dialog.api_key_input.setText("sk-ui-secret")
        dialog.model_input.setText("test-model")
        dialog.startup_input.setChecked(True)
        dialog.button_box.button(QDialogButtonBox.StandardButton.Save).click()

    QTimer.singleShot(0, save_settings)
    widget.title_bar.settings_button.click()

    assert not widget.settings.display.show_later_count
    assert not service.load().display.show_later_count
    assert service.load().ai.enabled
    assert service.load().ai.model == "test-model"
    assert credentials.saved == ["sk-ui-secret"]
    assert startup.calls == [True]
    assert service.load().startup.start_with_windows
    assert "sk-ui-secret" not in service.settings_file.read_text(encoding="utf-8")
    assert "After 3 Days" not in widget.summary_label.text()


def test_startup_failure_does_not_persist_setting(qtbot, tmp_path, monkeypatch):
    service = SettingsService(AppPaths(tmp_path))
    startup = FakeStartupService(succeeds=False)
    widget = MainWidget(service, startup_service=startup)
    qtbot.addWidget(widget)
    warnings = []
    monkeypatch.setattr(
        "app.ui.main_widget.QMessageBox.warning",
        lambda *args: warnings.append(args[2]),
    )

    def save_settings() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, SettingsDialog)
        dialog.startup_input.setChecked(True)
        dialog.button_box.button(QDialogButtonBox.StandardButton.Save).click()

    QTimer.singleShot(0, save_settings)
    widget.open_settings()

    assert startup.calls == [True]
    assert not service.load().startup.start_with_windows
    assert warnings == ["The Windows startup setting could not be updated."]


def test_enabled_startup_is_reconciled_when_widget_starts(qtbot, tmp_path):
    service = SettingsService(AppPaths(tmp_path))
    settings = service.load()
    settings.startup.start_with_windows = True
    assert service.save(settings)
    startup = FakeStartupService()

    widget = MainWidget(service, startup_service=startup)
    qtbot.addWidget(widget)

    assert startup.calls == [True]
