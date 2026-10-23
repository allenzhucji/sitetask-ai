from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class NaturalLanguageInputWidget(QWidget):
    parse_requested = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("aiInputWidget")

        heading = QLabel("✦ AI Task")
        heading.setObjectName("aiTaskHeading")
        self.text_input = QLineEdit()
        self.text_input.setObjectName("aiTaskText")
        self.text_input.setPlaceholderText("Tomorrow 3pm reply IRF-023")
        self.parse_button = QPushButton("Parse Task")
        self.parse_button.setObjectName("parseTaskButton")
        self.parse_button.clicked.connect(self._submit)
        self.text_input.returnPressed.connect(self._submit)

        self.status_label = QLabel()
        self.status_label.setObjectName("aiTaskStatus")
        self.status_label.setWordWrap(True)
        self.status_label.hide()

        input_layout = QHBoxLayout()
        input_layout.setContentsMargins(0, 0, 0, 0)
        input_layout.addWidget(self.text_input, 1)
        input_layout.addWidget(self.parse_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 9, 10, 9)
        layout.setSpacing(6)
        layout.addWidget(heading)
        layout.addLayout(input_layout)
        layout.addWidget(self.status_label)

    def clear_input(self) -> None:
        self.text_input.clear()

    def focus_input(self) -> None:
        self.text_input.setFocus()
        self.text_input.selectAll()

    def show_message(self, message: str, *, error: bool = False) -> None:
        self.status_label.setText(message)
        self.status_label.setStyleSheet(
            "color: #e07a7a;" if error else "color: #79c2bb;"
        )
        self.status_label.show()

    def _submit(self) -> None:
        text = self.text_input.text().strip()
        if not text:
            self.show_message("请输入任务内容。", error=True)
            return
        self.parse_requested.emit(text)
