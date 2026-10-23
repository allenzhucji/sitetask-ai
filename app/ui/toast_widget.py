from __future__ import annotations

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton


class ToastWidget(QFrame):
    undo_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("toastWidget")

        self.message_label = QLabel()
        self.message_label.setObjectName("toastMessage")
        self.undo_button = QPushButton("Undo")
        self.undo_button.setObjectName("toastUndoButton")
        self.undo_button.clicked.connect(self._request_undo)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 8, 8)
        layout.addWidget(self.message_label, 1)
        layout.addWidget(self.undo_button)

        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.setInterval(5_000)
        self.hide_timer.timeout.connect(self.hide)
        self.hide()

    def show_undo(self, message: str) -> None:
        self.message_label.setText(message)
        self.show()
        self.hide_timer.start()

    def dismiss(self) -> None:
        self.hide_timer.stop()
        self.hide()

    def _request_undo(self) -> None:
        self.undo_requested.emit()
        self.dismiss()
