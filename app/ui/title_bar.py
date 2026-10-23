from __future__ import annotations

from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from app.ui.icon_factory import IconName, make_flat_icon


class TitleBar(QWidget):
    pin_requested = Signal(bool)
    all_tasks_requested = Signal()
    settings_requested = Signal()
    minimize_requested = Signal()
    close_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._drag_offset: QPoint | None = None
        self.setObjectName("titleBar")
        # 紧凑标题栏：高度 32、顶部留空 2px，按钮贴顶不居中
        self.setFixedHeight(32)

        self.title_label = QLabel("SiteTask AI")
        self.title_label.setObjectName("titleLabel")

        self.pin_button = self._make_button(
            "pinButton",
            "Pin window on top",
            "pin",
            checkable=True,
        )
        self.set_pinned(False)

        self.all_tasks_button = self._make_button(
            "allTasksButton", "View All Tasks", "tasks"
        )
        self.settings_button = self._make_button(
            "settingsButton", "Settings", "settings"
        )
        self.minimize_button = self._make_button(
            "minimizeButton", "Minimize", "minimize"
        )
        self.close_button = self._make_button(
            "closeButton", "Close", "close"
        )

        layout = QHBoxLayout(self)
        # top/bottom 对称：按钮与左侧文字垂直居中对齐；右边距小，按钮组贴右
        layout.setContentsMargins(10, 3, 2, 3)
        layout.setSpacing(2)
        layout.addWidget(self.title_label)
        layout.addStretch(1)
        layout.addWidget(self.pin_button)
        layout.addWidget(self.all_tasks_button)
        layout.addWidget(self.settings_button)
        layout.addWidget(self.minimize_button)
        layout.addWidget(self.close_button)

        self.pin_button.clicked.connect(self.pin_requested)
        self.all_tasks_button.clicked.connect(self.all_tasks_requested)
        self.settings_button.clicked.connect(self.settings_requested)
        self.minimize_button.clicked.connect(self.minimize_requested)
        self.close_button.clicked.connect(self.close_requested)

    @staticmethod
    def _make_button(
        object_name: str,
        tooltip: str,
        icon_name: IconName,
        *,
        checkable: bool = False,
    ) -> QPushButton:
        button = QPushButton()
        button.setObjectName(object_name)
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        button.setCheckable(checkable)
        button.setFlat(True)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        # 图标显示大小保持 18x18，按钮外框 18x18 恰好包住图标
        button.setFixedSize(18, 18)
        button.setIconSize(QSize(18, 18))
        button.setIcon(make_flat_icon(icon_name, checkable=checkable))
        return button

    def set_pinned(self, pinned: bool) -> None:
        self.pin_button.setChecked(pinned)
        self.pin_button.setToolTip("Unpin window" if pinned else "Pin window on top")
        self.pin_button.setAccessibleName("Pinned" if pinned else "Not pinned")

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            window = self.window()
            self._drag_offset = event.globalPosition().toPoint() - window.pos()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if (
            self._drag_offset is not None
            and event.buttons() & Qt.MouseButton.LeftButton
        ):
            self.window().move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = None
            event.accept()
            return
        super().mouseReleaseEvent(event)
