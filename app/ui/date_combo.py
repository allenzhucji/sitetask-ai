from __future__ import annotations

from bisect import bisect_left
from datetime import date, timedelta

from PySide6.QtCore import QDate, QEvent, Qt, Signal
from PySide6.QtWidgets import QAbstractItemView, QComboBox


class DateComboBox(QComboBox):
    """滚动日期选择：下拉列表按日排列。

    打开时可见 7 行（前后各 3 天）且当前选中日期居中；在弹出列表上
    滚轮滚动 = 切换选中日期并保持居中。列表宽度与控件一致。

    对外提供与 QDateEdit 兼容的 date()/setDate()/dateChanged，
    便于调用方互换。列表外日期（如很久以前）setDate 时按序
    动态插入，保证任何日期都可选。
    """

    # 列表范围保持宽（可滚动到远处日期）；打开时只显示 7 行（见 VISIBLE_ROWS）
    PAST_DAYS = 60
    FUTURE_DAYS = 60
    VISIBLE_ROWS = 7  # 打开时可见：前后各 3 天 + 选中日

    dateChanged = Signal(QDate)

    def __init__(self, *, today: date) -> None:
        super().__init__()
        # 同时保留直接输入 YYYY-MM-DD 和下拉滚轮选择。NoInsert 避免
        # QComboBox 自动把未验证文本塞进模型；有效日期由 setDate 按序
        # 插入，远期日期因此也可继续直接输入。
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.setCompleter(None)
        self._line_edit = self.lineEdit()
        self._line_edit.setPlaceholderText("YYYY-MM-DD")
        self.setMaxVisibleItems(self.VISIBLE_ROWS)
        # 隐藏弹出列表滚动条（picker 式滚动菜单，无滚动条观感）
        self.view().setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._rebuild(today)
        self.currentIndexChanged.connect(self._emit_date_changed)
        self._line_edit.editingFinished.connect(self._commit_typed_date)
        self._line_edit.returnPressed.connect(self._commit_typed_date)
        self._line_edit.textEdited.connect(self._commit_typed_date)
        # 弹出列表滚轮：改变选中日期而不是滚动视图。
        # 真实滚轮事件（Windows WM_MOUSEWHEEL）的目标是 viewport（鼠标在列表上时），
        # 或 combo 自身（popup 打开但鼠标还停在日期框上时）；popup 容器 QFrame
        # 在 popup 打开前不存在（__init__ 时 view().parentWidget() 是 combo 自身），
        # 故容器过滤器在 showPopup 里装。三个目标都装，保证任何位置滚轮都生效。
        self.installEventFilter(self)
        self._line_edit.installEventFilter(self)
        self.view().viewport().installEventFilter(self)
        self._filtered_containers: set = set()

    def _rebuild(self, today: date) -> None:
        self.blockSignals(True)
        self.clear()
        for offset in range(-self.PAST_DAYS, self.FUTURE_DAYS + 1):
            day = today + timedelta(days=offset)
            self.addItem(day.isoformat(), day)
        self.blockSignals(False)

    def showPopup(self) -> None:
        super().showPopup()
        container = self.view().parentWidget()
        if container is not None and container not in self._filtered_containers:
            container.installEventFilter(self)
            self._filtered_containers.add(container)
        # 打开时选中日期居中（可见 7 行 = 前后各 3 天）。
        self.view().scrollTo(
            self.view().currentIndex(),
            QAbstractItemView.ScrollHint.PositionAtCenter,
        )

    def eventFilter(self, obj, event) -> bool:
        if obj is self._line_edit:
            if event.type() == QEvent.Type.FocusOut:
                self._commit_typed_date()
            elif event.type() == QEvent.Type.KeyPress and event.key() in (
                Qt.Key.Key_Return,
                Qt.Key.Key_Enter,
            ):
                self._commit_typed_date()
        if event.type() == QEvent.Type.Wheel:
            is_list = (
                obj is self.view().viewport()
                or obj is self.view().parentWidget()
            )
            is_self = obj is self and self.view().isVisible()  # popup 打开时
            if (is_list or is_self) and event.angleDelta().y():
                delta = event.angleDelta().y()
                index = self.currentIndex() + (1 if delta < 0 else -1)
                index = max(0, min(self.count() - 1, index))
                if index != self.currentIndex():
                    self.setCurrentIndex(index)
                self.view().scrollTo(
                    self.view().currentIndex(),
                    QAbstractItemView.ScrollHint.PositionAtCenter,
                )
                event.accept()
                return True
        return super().eventFilter(obj, event)

    def date(self) -> QDate:
        # 直接读取编辑框，确保尚未失焦/按 Enter 的手动输入也能立即用于
        # Quick Add 提交；无效文本返回 invalid QDate，不静默回退旧日期。
        return QDate.fromString(self.currentText().strip(), "yyyy-MM-dd")

    def setDate(self, value: QDate) -> None:
        target = value.toPython()
        target_text = target.isoformat()
        # PySide 的 QVariant 日期转换会让 findData(datetime.date) 在部分
        # 环境中匹配失败，导致列表已有日期仍被再次插入。日期文本是控件
        # 的稳定显示键，按 ISO 文本精确匹配可保证同一天只出现一次。
        index = self.findText(target_text, Qt.MatchFlag.MatchExactly)
        if index < 0:
            dates = [date.fromisoformat(self.itemText(i)) for i in range(self.count())]
            index = bisect_left(dates, target)
            self.blockSignals(True)
            self.insertItem(index, target_text, target)
            self.blockSignals(False)
        self.setCurrentIndex(index)

    def _emit_date_changed(self, _index: int) -> None:
        value = self.date()
        if value.isValid():
            self.dateChanged.emit(value)

    def _commit_typed_date(self, _text: str | None = None) -> None:
        value = QDate.fromString(self.currentText().strip(), "yyyy-MM-dd")
        if value.isValid():
            self.setDate(value)
