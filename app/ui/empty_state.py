from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget


class EmptyStateWidget(QWidget):
    def __init__(self, title: str, message: str, *, show_later_button: bool) -> None:
        super().__init__()
        self.setObjectName("emptyState")

        self.title_label = QLabel(title)
        self.title_label.setObjectName("emptyStateTitle")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.message_label = QLabel(message)
        self.message_label.setObjectName("emptyStateMessage")
        self.message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message_label.setWordWrap(True)

        self.view_later_button = QPushButton("View Later Tasks")
        self.view_later_button.setObjectName("viewLaterButton")
        self.view_later_button.setEnabled(False)
        self.view_later_button.setVisible(show_later_button)
        self.view_later_button.setToolTip("All Tasks will be added in stage 7")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 48, 28, 28)
        layout.setSpacing(10)
        layout.addStretch(1)
        layout.addWidget(self.title_label)
        layout.addWidget(self.message_label)
        layout.addWidget(self.view_later_button, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch(2)
