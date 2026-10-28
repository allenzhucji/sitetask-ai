from __future__ import annotations

from PySide6.QtCore import QTime, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import ComboBox

from app.models.settings import Settings
from app.models.task import Category, Priority
from app.services.ai_task_parser import AIParseError, OpenAITaskParser
from app.services.credential_service import CredentialService


class SettingsDialog(QDialog):
    def __init__(
        self,
        settings: Settings,
        parent: QWidget | None = None,
        *,
        credential_service: CredentialService | None = None,
        connection_tester: OpenAITaskParser | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings.model_copy(deep=True)
        self.credential_service = credential_service or CredentialService()
        self.connection_tester = connection_tester or OpenAITaskParser()
        self.setWindowTitle("Settings")
        self.setModal(True)
        self.setMinimumWidth(360)

        self.close_to_tray_input = QCheckBox("Hide instead of closing")
        self.close_to_tray_input.setChecked(settings.window.close_to_tray)

        # 主背景不透明度（40-95%，对应 background_opacity 0.4-0.95）
        self.background_opacity_input = QSlider(Qt.Orientation.Horizontal)
        self.background_opacity_input.setRange(40, 95)
        self.background_opacity_input.setValue(
            round(settings.window.background_opacity * 100)
        )
        self.opacity_value_label = QLabel()
        opacity_row = QWidget()
        opacity_layout = QHBoxLayout(opacity_row)
        opacity_layout.setContentsMargins(0, 0, 0, 0)
        opacity_layout.setSpacing(8)
        opacity_layout.addWidget(self.background_opacity_input, 1)
        opacity_layout.addWidget(self.opacity_value_label)
        self.background_opacity_input.valueChanged.connect(
            self._update_opacity_label
        )
        self._update_opacity_label()

        self.show_overdue_input = QCheckBox("Show No Due tasks")
        self.show_overdue_input.setChecked(settings.display.show_overdue)
        self.show_later_count_input = QCheckBox("Show Later count")
        self.show_later_count_input.setChecked(settings.display.show_later_count)

        self.apply_default_time_input = QCheckBox("Apply default time")
        self.apply_default_time_input.setChecked(
            settings.task_defaults.apply_default_time
        )
        hour, minute = map(int, settings.task_defaults.default_due_time.split(":"))
        # 原生 QTimeEdit（同 quick_add_widget，Fluent TimeEdit 在 PySide6
        # 移植版下文本渲染不可靠）
        self.default_due_time_input = QTimeEdit()
        self.default_due_time_input.setTime(QTime(hour, minute))
        self.default_due_time_input.setDisplayFormat("HH:mm")

        self.default_category_input = ComboBox()
        self.default_category_input.addItems([str(value) for value in Category])
        self.default_category_input.setCurrentText(settings.task_defaults.default_category)
        self.default_priority_input = ComboBox()
        self.default_priority_input.addItems([str(value) for value in Priority])
        self.default_priority_input.setCurrentText(settings.task_defaults.default_priority)

        self.notifications_input = QCheckBox("Enable notifications")
        self.notifications_input.setChecked(settings.notifications.enabled)
        self.startup_input = QCheckBox("Start with Windows")
        self.startup_input.setChecked(settings.startup.start_with_windows)

        self.ai_enabled_input = QCheckBox("Enable AI Parsing")
        self.ai_enabled_input.setChecked(settings.ai.enabled)
        self.api_key_input = QLineEdit()
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_input.setClearButtonEnabled(True)
        masked_key = self.credential_service.masked_api_key()
        self.api_key_input.setPlaceholderText(
            f"Stored securely: {masked_key}" if masked_key else "Not configured"
        )
        self.model_input = QLineEdit(settings.ai.model)
        self.model_input.setPlaceholderText("Enter an OpenAI model ID")
        self.local_threshold_input = QDoubleSpinBox()
        self.local_threshold_input.setRange(0.0, 1.0)
        self.local_threshold_input.setSingleStep(0.05)
        self.local_threshold_input.setDecimals(2)
        self.local_threshold_input.setValue(settings.ai.local_parser_threshold)
        self.test_connection_button = QPushButton("Test Connection")
        self.test_connection_button.clicked.connect(self._test_connection)
        self.connection_status_label = QLabel()
        self.connection_status_label.setWordWrap(True)
        self.connection_status_label.hide()

        form = QFormLayout()
        form.addRow("Close to tray", self.close_to_tray_input)
        form.addRow("Background opacity", opacity_row)
        form.addRow("", self.show_overdue_input)
        form.addRow("", self.show_later_count_input)
        form.addRow("", self.apply_default_time_input)
        form.addRow("Default due time", self.default_due_time_input)
        form.addRow("Default category", self.default_category_input)
        form.addRow("Default priority", self.default_priority_input)
        form.addRow("", self.notifications_input)
        form.addRow("", self.startup_input)
        form.addRow("", self.ai_enabled_input)
        form.addRow("API Key", self.api_key_input)
        form.addRow("Model", self.model_input)
        form.addRow("Local parser threshold", self.local_threshold_input)
        form.addRow("", self.test_connection_button)
        form.addRow("", self.connection_status_label)

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        if parent is not None and hasattr(parent, 'cloud_bridge'):
            from app.ui.cloud_settings_dialog import CloudSettingsDialog
            cloud_button = QPushButton('Cloud bridge…')
            cloud_button.clicked.connect(lambda: CloudSettingsDialog(parent.cloud_bridge, self).exec())
            layout.addWidget(cloud_button)
        layout.addWidget(self.button_box)

    def _update_opacity_label(self) -> None:
        self.opacity_value_label.setText(
            f"{self.background_opacity_input.value()}%"
        )

    def result_settings(self) -> Settings:
        settings = self._settings.model_copy(deep=True)
        settings.window.close_to_tray = self.close_to_tray_input.isChecked()
        settings.window.background_opacity = (
            self.background_opacity_input.value() / 100
        )
        settings.display.show_overdue = self.show_overdue_input.isChecked()
        settings.display.show_later_count = self.show_later_count_input.isChecked()
        settings.task_defaults.apply_default_time = (
            self.apply_default_time_input.isChecked()
        )
        settings.task_defaults.default_due_time = (
            self.default_due_time_input.time().toString("HH:mm")
        )
        settings.task_defaults.default_category = self.default_category_input.currentText()
        settings.task_defaults.default_priority = self.default_priority_input.currentText()
        settings.notifications.enabled = self.notifications_input.isChecked()
        settings.startup.start_with_windows = self.startup_input.isChecked()
        settings.ai.enabled = self.ai_enabled_input.isChecked()
        settings.ai.model = self.model_input.text().strip()
        settings.ai.local_parser_threshold = self.local_threshold_input.value()
        return settings

    def save_pending_api_key(self) -> bool:
        api_key = self.api_key_input.text().strip()
        if not api_key:
            return True
        return self.credential_service.save_api_key(api_key)

    def _test_connection(self) -> None:
        api_key = self.api_key_input.text().strip()
        if not api_key:
            api_key = self.credential_service.get_api_key() or ""
        model = self.model_input.text().strip()
        if not api_key:
            self._show_connection_status(
                "API key is not configured.",
                error=True,
            )
            return
        if not model:
            self._show_connection_status("Enter a model first.", error=True)
            return

        self.test_connection_button.setEnabled(False)
        try:
            self.connection_tester.test_connection(api_key=api_key, model=model)
        except AIParseError as error:
            self._show_connection_status(str(error), error=True)
        else:
            self._show_connection_status("Connection successful.", error=False)
        finally:
            self.test_connection_button.setEnabled(True)

    def _show_connection_status(self, message: str, *, error: bool) -> None:
        self.connection_status_label.setText(message)
        self.connection_status_label.setStyleSheet(
            "color: #e07a7a;" if error else "color: #79c2bb;"
        )
        self.connection_status_label.show()
