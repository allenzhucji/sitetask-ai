from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date, datetime, timedelta

from PySide6.QtCore import QPoint, QRectF, QTimer, Qt
from PySide6.QtGui import (
    QCloseEvent,
    QColor,
    QCursor,
    QGuiApplication,
    QMouseEvent,
    QMoveEvent,
    QPaintEvent,
    QPainter,
    QResizeEvent,
    QShowEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.database.connection import Database
from app.database.task_repository import TaskRepository
from app.models.task import (
    Category,
    Priority,
    Task,
    TaskStatus,
    TaskSource,
    current_local_datetime,
)
from app.services.settings_service import SettingsService
from app.services.local_identity import IdentityStatus, LocalIdentityService
from app.services.local_queue import LocalTaskQueue
from app.services.cloud_bridge import CloudBridgeController
from app.services.local_task_parser import LocalTaskParser
from app.services.ai_task_parser import OpenAITaskParser
from app.services.credential_service import CredentialService
from app.services.parser_router import ParserRouter
from app.services.startup_service import StartupService
from app.ui.ai_input_widget import NaturalLanguageInputWidget
from app.ui.all_tasks_dialog import AllTasksDialog
from app.ui.empty_state import EmptyStateWidget
from app.ui.quick_add_widget import QuickAddWidget
from app.ui.settings_dialog import SettingsDialog
from app.ui.task_item import TaskItem
from app.ui.task_editor_dialog import TaskEditorDialog
from app.ui.task_tooltip import refresh_description_popup
from app.ui.task_section import TaskSection
from app.ui.task_preview_dialog import TaskPreviewDialog
from app.ui.title_bar import TitleBar
from app.ui.toast_widget import ToastWidget
from app.utils.validation import (
    normalize_task_title,
    parse_due_date,
    parse_optional_due_time,
)


class MainWidget(QWidget):
    DEFAULT_WIDTH = 400
    DEFAULT_HEIGHT = 700
    MINIMUM_WIDTH = 340
    MINIMUM_HEIGHT = 480
    RESIZE_MARGIN = 6

    def __init__(
        self,
        settings_service: SettingsService | None = None,
        repository: TaskRepository | None = None,
        today_provider: Callable[[], date] = date.today,
        now_provider: Callable[[], datetime] = current_local_datetime,
        credential_service: CredentialService | None = None,
        ai_parser: OpenAITaskParser | None = None,
        startup_service: StartupService | None = None,
    ) -> None:
        super().__init__()
        self.settings_service = settings_service or SettingsService()
        self.settings = self.settings_service.load()
        self.repository = repository or TaskRepository(
            Database(self.settings_service.paths.database_file)
        )
        self.today_provider = today_provider
        self.now_provider = now_provider
        self.credential_service = credential_service or CredentialService()
        self.ai_parser = ai_parser or OpenAITaskParser()
        self.startup_service = startup_service or StartupService()
        if self.settings.startup.start_with_windows:
            self.startup_service.enable()
        self.sections: list[TaskSection] = []
        self.empty_drop_targets: list[TaskSection] = []
        self.empty_state: EmptyStateWidget | None = None
        self._is_pinned = self.settings.window.is_pinned
        self.all_tasks_dialog: AllTasksDialog | None = None
        self._tray_available = False
        self._force_exit = False
        self.notifications_paused = False

        self.resize_save_timer = QTimer(self)
        self.resize_save_timer.setSingleShot(True)
        self.resize_save_timer.setInterval(250)
        self.resize_save_timer.timeout.connect(self._save_window_state)

        self.setObjectName("mainWidget")
        self.setAttribute(Qt.WidgetAttribute.WA_AlwaysShowToolTips, True)
        self.setWindowTitle("SiteTask AI")
        window_flags = Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
        if self._is_pinned:
            window_flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(window_flags)
        # 半透明磨砂背景：允许 per-pixel alpha，背景由 paintEvent
        # 以固定 alpha 绘制（无实时抓屏采样）
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMinimumSize(self.MINIMUM_WIDTH, self.MINIMUM_HEIGHT)
        self.setMouseTracking(True)
        # 边框 resize 光标状态机：Qt 只在鼠标下的控件变化或控件开启
        # mouseTracking 时才派发 MouseMove，子控件上的移动事件到不了
        # 主窗口；因此每 60ms 按真实光标位置刷新主窗口光标（移出边框
        # 立即恢复箭头，不会停在拉伸状态）。setCursor 相同值会跳过，
        # 开销可忽略
        self.cursor_poll_timer = QTimer(self)
        self.cursor_poll_timer.setInterval(60)
        self.cursor_poll_timer.timeout.connect(self._refresh_cursor_from_global)
        self.cursor_poll_timer.start()
        self.resize(self.settings.window.width, self.settings.window.height)

        self.title_bar = TitleBar(self)
        self.title_bar.set_pinned(self._is_pinned)
        self.title_bar.pin_requested.connect(self.set_pinned)
        self.title_bar.all_tasks_requested.connect(self.open_all_tasks)
        self.title_bar.settings_requested.connect(self.open_settings)
        self.title_bar.minimize_requested.connect(self.minimize_or_hide)
        self.title_bar.close_requested.connect(self.close)

        self.summary_label = QLabel()
        self.summary_label.setObjectName("taskSummary")
        self.summary_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )

        self.task_container = QWidget()
        self.task_container.setObjectName("taskContainer")
        self.task_container.setMinimumWidth(0)
        self.task_list_layout = QVBoxLayout(self.task_container)
        self.task_list_layout.setContentsMargins(0, 0, 0, 0)
        self.task_list_layout.setSpacing(2)

        self.task_scroll_area = QScrollArea()
        self.task_scroll_area.setObjectName("taskScrollArea")
        self.task_scroll_area.setWidgetResizable(True)
        self.task_scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)
        self.task_scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.task_scroll_area.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.task_scroll_area.setWidget(self.task_container)

        self.quick_add = QuickAddWidget(
            today_provider=self.today_provider,
            default_due_time=self.settings.task_defaults.default_due_time,
        )
        self.quick_add.submitted.connect(self._add_quick_task)
        self.quick_add.full_editor_requested.connect(self.open_task_editor)

        self.ai_input = NaturalLanguageInputWidget()
        self.ai_input.parse_requested.connect(self._parse_natural_task)

        self.input_panel = QWidget()
        self.input_panel.setObjectName("taskInputPanel")
        input_panel_layout = QVBoxLayout(self.input_panel)
        input_panel_layout.setContentsMargins(0, 0, 0, 0)
        input_panel_layout.setSpacing(0)
        input_panel_layout.addWidget(self.quick_add)
        input_panel_layout.addWidget(self.ai_input)

        self.input_panel_toggle_button = QPushButton("＋ Add Task")
        self.input_panel_toggle_button.setObjectName("taskInputToggleButton")
        self.input_panel_toggle_button.setCheckable(True)
        self.input_panel_toggle_button.setToolTip("Show Quick Task and AI Task")
        self.input_panel_toggle_button.toggled.connect(
            self.set_input_panel_expanded
        )

        self.input_toggle_bar = QWidget()
        self.input_toggle_bar.setObjectName("inputToggleBar")
        input_toggle_layout = QHBoxLayout(self.input_toggle_bar)
        input_toggle_layout.setContentsMargins(6, 4, 6, 2)
        input_toggle_layout.addWidget(self.summary_label)
        input_toggle_layout.addStretch(1)
        input_toggle_layout.addWidget(self.input_panel_toggle_button)

        self.toast = ToastWidget()
        self.toast.undo_requested.connect(self._undo_last_completion)

        self.root_layout = QVBoxLayout(self)
        self.root_layout.setContentsMargins(
            self.RESIZE_MARGIN,
            self.RESIZE_MARGIN,
            self.RESIZE_MARGIN,
            self.RESIZE_MARGIN,
        )
        self.root_layout.setSpacing(0)
        self.root_layout.addWidget(self.title_bar)
        self.root_layout.addWidget(self.task_scroll_area, 1)
        self.root_layout.addWidget(self.input_panel)
        self.root_layout.addWidget(self.toast)
        self.root_layout.addWidget(self.input_toggle_bar)

        self.set_input_panel_expanded(False)

        self._restore_position()
        self.refresh_tasks()

        self.refresh_timer = QTimer(self)
        self.refresh_timer.setObjectName("taskRefreshTimer")
        self.refresh_timer.setInterval(60_000)
        self.refresh_timer.timeout.connect(self.refresh_tasks)
        self.refresh_timer.start()

        self.completion_refresh_timer = QTimer(self)
        self.completion_refresh_timer.setSingleShot(True)
        self.completion_refresh_timer.setInterval(2_000)
        self.completion_refresh_timer.timeout.connect(self.refresh_tasks)
        self.last_completed_task_id: int | None = None

        self.identity_check = self._check_local_identity()

        self.local_queue = LocalTaskQueue(
            self.repository, self.settings_service.paths.root,
            busy=self._queue_interaction_busy, changed=self._queue_refresh,
        )
        self.local_queue_timer = QTimer(self)
        self.local_queue_timer.setInterval(1000)
        self.cloud_bridge = CloudBridgeController(self.repository, self.settings_service.paths, self.local_queue, self)
        self.cloud_bridge.startup()
        self.local_queue_timer.timeout.connect(self.cloud_bridge.cycle)
        application = QApplication.instance()
        if application is not None:
            application.aboutToQuit.connect(self.cloud_bridge.stop)
        self.local_queue_timer.start()
        self.destroyed.connect(lambda queue=self.local_queue: queue.close())

    def _check_local_identity(self):
        try:
            service = LocalIdentityService(self.settings_service.paths, self.repository.database)
            result = service.record()
            if result.status not in (IdentityStatus.NEW, IdentityStatus.PAIRED):
                logging.getLogger("sitetask").warning("Local database identity: %s", result.status)
            return result
        except Exception:
            logging.getLogger("sitetask").warning("Local identity check failed", exc_info=True)
            return None

    def _queue_interaction_busy(self) -> bool:
        return bool(
            QApplication.activeModalWidget() or QApplication.activePopupWidget()
            or QApplication.mouseButtons() != Qt.MouseButton.NoButton
            or getattr(self, '_task_drag_active', False)
            or self.completion_refresh_timer.isActive()
            or any(isinstance(w, (TaskEditorDialog, TaskPreviewDialog)) and w.isVisible()
                   for w in QApplication.topLevelWidgets())
            or (self.isActiveWindow() and
                (self.quick_add.title_input.text().strip() or self.ai_input.text_input.text().strip()))
        )

    def _queue_refresh(self) -> None:
        selected = self.all_tasks_dialog.selected_task() if self.all_tasks_dialog else None
        self.refresh_tasks()
        if selected and self.all_tasks_dialog:
            self.all_tasks_dialog.select_task(selected.id)

    @property
    def is_pinned(self) -> bool:
        return self._is_pinned

    def set_pinned(self, pinned: bool) -> None:
        pinned = bool(pinned)
        position = self.pos()
        size = self.size()
        was_visible = self.isVisible()

        window_flags = self.windowFlags()
        if pinned:
            window_flags |= Qt.WindowType.WindowStaysOnTopHint
        else:
            window_flags &= ~Qt.WindowType.WindowStaysOnTopHint

        self._is_pinned = pinned
        self.setWindowFlags(window_flags)
        if was_visible:
            self.show()
        self.resize(size)
        self.move(position)
        if was_visible:
            self.raise_()
            self.activateWindow()

        self.title_bar.set_pinned(pinned)
        self._save_window_state(position=position, size=size)
        self.refresh_tasks()

    def paintEvent(self, event: QPaintEvent) -> None:
        """绘制圆角半透明磨砂背景。

        Qt 对顶层窗口不绘制 QSS 背景（QStyleSheetStyle 的 PE_Widget 对
        isWindow() 跳过），因此主背景由 QPainter 直接画：固定 alpha 的
        深色圆角，呈现磨砂观感（无实时抓屏采样）。
        """
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(23, 25, 31)
        # 不透明度取自设置（0.4-0.95），保存设置后 update() 即时生效
        color.setAlpha(round(255 * self.settings.window.background_opacity))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawRoundedRect(self.rect(), 10, 10)

    def refresh_tasks(self) -> None:
        self.quick_add.refresh_date_if_auto()
        scroll_position = self.task_scroll_area.verticalScrollBar().value()
        while self.task_list_layout.count():
            item = self.task_list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        today = self.today_provider()
        visible_tasks = self.repository.list_widget_tasks(
            today,
            self.settings.display.days_ahead,
        )
        if not self.settings.display.show_overdue:
            visible_tasks = [
                task
                for task in visible_tasks
                if not task.no_due and task.due_date >= today
            ]

        later_count = self._refresh_summary_counts(today)

        grouped_tasks = (
            (
                "NO DUE",
                [
                    task
                    for task in visible_tasks
                    if task.no_due or task.due_date < today
                ],
                None,
                True,
                True,
                True,
            ),
            (
                "TODAY",
                [
                    task
                    for task in visible_tasks
                    if not task.no_due and task.due_date == today
                ],
                today,
                True,
                False,
                False,
            ),
            (
                "TOMORROW",
                [task for task in visible_tasks if not task.no_due and task.due_date == today + timedelta(days=1)],
                today + timedelta(days=1),
                True,
                False,
                False,
            ),
            (
                "DAY AFTER TOMORROW",
                [task for task in visible_tasks if not task.no_due and task.due_date == today + timedelta(days=2)],
                today + timedelta(days=2),
                True,
                False,
                False,
            ),
        )

        self.sections = []
        self.empty_drop_targets = []
        self.empty_state = None
        for (
            title,
            tasks,
            section_due_date,
            accepts_drops,
            no_due_target,
            always_visible,
        ) in grouped_tasks:
            section = TaskSection(
                title,
                tasks,
                today,
                due_date=section_due_date,
                no_due_target=no_due_target,
                items_draggable=True,
                accepts_drops=accepts_drops,
            )
            section.move_requested.connect(self._move_task)
            for task_item in section.task_items:
                self._connect_task_item(task_item)
            self.task_list_layout.addWidget(section)
            if tasks:
                self.sections.append(section)
            elif always_visible:
                # NO DUE is a permanent pinned drop lane, even when empty.
                pass
            else:
                self.empty_drop_targets.append(section)
                section.hide()

        if not self.sections:
            if later_count:
                self.empty_state = EmptyStateWidget(
                    "未来三天暂无任务",
                    f"还有 {later_count} 个后续任务",
                    show_later_button=True,
                )
            else:
                self.empty_state = EmptyStateWidget(
                    "暂无任务",
                    "使用 Quick Task 或 AI Task 添加任务",
                    show_later_button=False,
                )
            self.task_list_layout.addWidget(self.empty_state, 1)

        self.task_list_layout.addStretch(1)
        QTimer.singleShot(
            0,
            lambda: self.task_scroll_area.verticalScrollBar().setValue(scroll_position),
        )
        if self.all_tasks_dialog is not None and self.all_tasks_dialog.isVisible():
            self.all_tasks_dialog.refresh()

        refresh_description_popup(self, visible_tasks)

    def _refresh_summary_counts(self, today: date | None = None) -> int:
        """Refresh bottom counts immediately after task state changes."""
        today = today or self.today_provider()
        next_three_days_count = self.repository.count_widget_tasks(
            today,
            self.settings.display.days_ahead,
        )
        later_count = self.repository.count_later_tasks(
            today,
            self.settings.display.days_ahead,
        )
        summary = f"Next 3 Days：{next_three_days_count}"
        if self.settings.display.show_later_count:
            summary += f"\nAfter 3 Days：{later_count}"
        self.summary_label.setText(summary)
        return later_count

    def _connect_task_item(self, task_item: TaskItem) -> None:
        task_item.complete_requested.connect(self._complete_task)
        task_item.edit_requested.connect(self._edit_task)
        task_item.change_due_date_requested.connect(self._change_due_date)
        task_item.duplicate_requested.connect(self._duplicate_task)
        task_item.delete_requested.connect(self._delete_task)
        task_item.drag_started.connect(
            lambda: self._set_empty_drop_targets_visible(True)
        )
        task_item.drag_finished.connect(
            lambda: self._set_empty_drop_targets_visible(False)
        )

    def _move_task(
        self,
        task_id: int,
        target_due_date: date | None,
        target_ordered_task_ids: list[int],
        make_first_urgent: bool,
    ) -> None:
        make_first_urgent = (
            make_first_urgent
            and target_due_date is not None
            and target_due_date == self.today_provider()
            and bool(target_ordered_task_ids)
        )
        try:
            self.repository.move_task_to_date(
                task_id,
                target_due_date,
                target_ordered_task_ids,
                make_first_urgent=make_first_urgent,
                today=self.today_provider(),
            )
        except ValueError as error:
            QMessageBox.warning(self, "Unable to move task", str(error))
        # Defer refresh so widgets that started the drag are not deleted
        # mid-flight inside QDrag.exec()'s nested event loop.
        QTimer.singleShot(0, self.refresh_tasks)

    def _set_empty_drop_targets_visible(self, visible: bool) -> None:
        self._task_drag_active = visible
        for section in self.empty_drop_targets:
            section.set_empty_drop_target_visible(visible)

    def set_input_panel_expanded(self, expanded: bool) -> None:
        expanded = bool(expanded)
        self.input_panel.setVisible(expanded)
        self.quick_add.refresh_date_if_auto()
        self.input_panel_toggle_button.blockSignals(True)
        self.input_panel_toggle_button.setChecked(expanded)
        self.input_panel_toggle_button.blockSignals(False)
        self.input_panel_toggle_button.setText("Hide ▴" if expanded else "＋ Add Task")
        self.input_panel_toggle_button.setToolTip(
            "Hide Quick Task and AI Task"
            if expanded
            else "Show Quick Task and AI Task"
        )

    def _complete_task(self, task_id: int) -> None:
        completed = self.repository.complete_task(task_id)
        if completed is None:
            return
        for section in self.sections:
            for task_item in section.task_items:
                if task_item.task.id == task_id:
                    task_item.mark_completed()
                    break
        self.last_completed_task_id = task_id
        self._refresh_summary_counts()
        self.completion_refresh_timer.start()
        self.toast.show_undo("Task completed")
        if self.all_tasks_dialog is not None and self.all_tasks_dialog.isVisible():
            self.all_tasks_dialog.refresh()

    def _undo_last_completion(self) -> None:
        if self.last_completed_task_id is None:
            return
        restored = self.repository.restore_task(self.last_completed_task_id)
        self.completion_refresh_timer.stop()
        self.last_completed_task_id = None
        self.toast.dismiss()
        if restored is not None:
            self.refresh_tasks()

    def _restore_task(self, task_id: int) -> None:
        restored = self.repository.restore_task(task_id)
        if restored is None:
            return
        if self.last_completed_task_id == task_id:
            self.completion_refresh_timer.stop()
            self.last_completed_task_id = None
            self.toast.dismiss()
        self.refresh_tasks()

    def open_task_editor(self, task_id: int | None = None) -> None:
        task = self.repository.get_task(task_id)
        if task_id is not None and task is None:
            return
        dialog = TaskEditorDialog(
            task,
            default_category=self.settings.task_defaults.default_category,
            default_priority=self.settings.task_defaults.default_priority,
            today_provider=self.today_provider,
            parent=self,
        )
        if dialog.exec() != TaskEditorDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        now = self.now_provider()
        status = values["status"]
        completed_at = task.completed_at if task else None
        if status == TaskStatus.COMPLETED and completed_at is None:
            completed_at = now
        elif status != TaskStatus.COMPLETED:
            completed_at = None

        if task is None:
            self.repository.create_task(
                Task(
                    **values,
                    created_at=now,
                    updated_at=now,
                    completed_at=completed_at,
                )
            )
        else:
            self.repository.update_task(
                task.model_copy(update={**values, "completed_at": completed_at})
            )
        self.refresh_tasks()

    def open_all_tasks(self) -> None:
        if self.all_tasks_dialog is None:
            self.all_tasks_dialog = AllTasksDialog(
                self.repository,
                today_provider=self.today_provider,
                days_ahead=self.settings.display.days_ahead,
                parent=self,
            )
            self.all_tasks_dialog.edit_requested.connect(self.open_task_editor)
            self.all_tasks_dialog.complete_requested.connect(self._complete_task)
            self.all_tasks_dialog.restore_requested.connect(self._restore_task)
            self.all_tasks_dialog.delete_requested.connect(self._delete_task)
            self.all_tasks_dialog.undelete_requested.connect(self._undelete_task)
            self.all_tasks_dialog.purge_requested.connect(self._purge_deleted_tasks)
        self.all_tasks_dialog.refresh()
        self.all_tasks_dialog.show()
        self.all_tasks_dialog.raise_()
        self.all_tasks_dialog.activateWindow()

    def open_settings(self) -> None:
        dialog = SettingsDialog(
            self.settings,
            self,
            credential_service=self.credential_service,
            connection_tester=self.ai_parser,
        )
        if dialog.exec() != SettingsDialog.DialogCode.Accepted:
            return
        updated_settings = dialog.result_settings()
        if not dialog.save_pending_api_key():
            QMessageBox.warning(
                self,
                "Settings",
                "The API key could not be saved securely.",
            )
            return
        startup_changed = (
            updated_settings.startup.start_with_windows
            != self.settings.startup.start_with_windows
        )
        if startup_changed and not self.startup_service.apply(
            updated_settings.startup.start_with_windows
        ):
            QMessageBox.warning(
                self,
                "Settings",
                "The Windows startup setting could not be updated.",
            )
            return
        if not self.settings_service.save(updated_settings):
            if startup_changed:
                self.startup_service.apply(
                    self.settings.startup.start_with_windows
                )
            QMessageBox.warning(self, "Settings", "Settings could not be saved.")
            return
        self.settings = updated_settings
        # 背景不透明度变化需立即重绘（paintEvent 读 self.settings）
        self.update()
        self.quick_add.set_default_due_time(
            self.settings.task_defaults.default_due_time
        )
        if self.all_tasks_dialog is not None:
            self.all_tasks_dialog.days_ahead = self.settings.display.days_ahead
        self.refresh_tasks()

    def focus_natural_input(self) -> None:
        self.show_from_tray()
        self.set_input_panel_expanded(True)
        self.ai_input.focus_input()

    def _parse_natural_task(self, original_text: str) -> None:
        router = ParserRouter(
            local_parser=LocalTaskParser(
                clock=self.now_provider,
                default_due_time=self.settings.task_defaults.default_due_time,
                apply_default_time=self.settings.task_defaults.apply_default_time,
            ),
            ai_parser=self.ai_parser,
            credential_service=self.credential_service,
            clock=self.now_provider,
        )
        try:
            result = router.parse(original_text, self.settings)
        except ValueError as error:
            self.ai_input.show_message(str(error), error=True)
            return

        preview = TaskPreviewDialog(result, self)
        if preview.exec() != TaskPreviewDialog.DialogCode.Accepted:
            return
        values = preview.values()
        now = self.now_provider()
        self.repository.create_task(
            Task(
                **values,
                source=(
                    TaskSource.AI
                    if result.parser_source == "ai"
                    else TaskSource.LOCAL_PARSER
                ),
                created_at=now,
                updated_at=now,
            )
        )
        self.ai_input.clear_input()
        visible_end = self.today_provider() + timedelta(
            days=self.settings.display.days_ahead - 1
        )
        if values["due_date"] > visible_end:
            self.ai_input.show_message(
                "任务已保存，将在进入未来三天范围后显示。"
            )
        else:
            self.ai_input.show_message("任务已添加。")
        self.refresh_tasks()

    def set_tray_available(self, available: bool) -> None:
        self._tray_available = bool(available)

    def set_notifications_paused(self, paused: bool) -> None:
        self.notifications_paused = bool(paused)

    def minimize_or_hide(self) -> None:
        if self._tray_available:
            self.hide()
        else:
            self.showMinimized()

    def show_from_tray(self) -> None:
        self.refresh_tasks()
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()
        self.raise_()
        self.activateWindow()

    def toggle_from_tray(self) -> None:
        if self.isVisible() and not self.isMinimized():
            self.hide()
        else:
            self.show_from_tray()

    def exit_application(self) -> None:
        self.cloud_bridge.stop()
        if self.cloud_bridge.thread and self.cloud_bridge.thread.isRunning():
            return
        self.local_queue.close()
        self._force_exit = True
        if self.all_tasks_dialog is not None:
            self.all_tasks_dialog.close()
        self.close()
        application = QApplication.instance()
        if application is not None:
            application.quit()

    def _edit_task(self, task_id: int) -> None:
        self.open_task_editor(task_id)

    def _change_due_date(self, task_id: int) -> None:
        task = self.repository.get_task(task_id)
        if task is None:
            return
        value, accepted = QInputDialog.getText(
            self,
            "Change Due Date",
            "Due date (YYYY-MM-DD)",
            QLineEdit.EchoMode.Normal,
            task.due_date.isoformat(),
        )
        if not accepted:
            return
        try:
            due_date = date.fromisoformat(value.strip())
        except ValueError:
            QMessageBox.warning(self, "Invalid Date", "Use YYYY-MM-DD format.")
            return
        self.repository.update_task(
            task.model_copy(update={"due_date": due_date, "no_due": False})
        )
        self.refresh_tasks()

    def _duplicate_task(self, task_id: int) -> None:
        if self.repository.duplicate_task(task_id) is not None:
            self.refresh_tasks()

    def _delete_task(self, task_id: int) -> None:
        task = self.repository.get_task(task_id)
        if task is None:
            return
        answer = QMessageBox.question(
            self,
            "Delete Task",
            f'Delete "{task.title}"?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.repository.delete_task(task_id)
            self.refresh_tasks()

    def _undelete_task(self, task_id: int) -> None:
        if self.repository.undelete_task(task_id) is not None:
            self.refresh_tasks()

    def _purge_deleted_tasks(self, task_ids: list[int]) -> None:
        """Permanent, local-only deletion from the recycle bin (never cloud-reachable)."""
        task_ids = [int(task_id) for task_id in task_ids]
        if not task_ids:
            return
        noun = "task" if len(task_ids) == 1 else f"{len(task_ids)} tasks"
        answer = QMessageBox.warning(
            self,
            "Delete Permanently",
            f"Permanently delete {noun} from the Recycle Bin?\n\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.repository.purge_deleted_tasks(task_ids)
        except ValueError:
            QMessageBox.warning(self, "Delete Permanently", "Only Recycle Bin tasks can be purged.")
        self.refresh_tasks()

    def _add_quick_task(self, title_text: str, date_text: str, time_text: str) -> None:
        try:
            title = normalize_task_title(title_text)
            due_date = parse_due_date(date_text)
            due_time = parse_optional_due_time(time_text)
        except ValueError as error:
            self.quick_add.show_message(str(error), error=True)
            return

        today = self.today_provider()
        if due_date < today:
            answer = QMessageBox.question(
                self,
                "Past Due Date",
                "截止日期早于今天，仍要添加吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                self.quick_add.show_message("任务未添加。")
                return

        try:
            category = Category(self.settings.task_defaults.default_category)
        except ValueError:
            category = Category.OTHER
        priority = Priority(self.settings.task_defaults.default_priority)
        now = self.now_provider()
        self.repository.create_task(
            Task(
                title=title,
                due_date=due_date,
                due_time=due_time,
                category=category,
                priority=priority,
                created_at=now,
                updated_at=now,
            )
        )
        self.quick_add.clear_inputs()
        visible_end_date = today + timedelta(days=self.settings.display.days_ahead - 1)
        if due_date > visible_end_date:
            self.quick_add.show_message("任务已保存，将在进入未来三天范围后显示。")
        else:
            self.quick_add.show_message("任务已添加。")
        self.refresh_tasks()

    def _restore_position(self) -> None:
        saved_x = self.settings.window.x
        saved_y = self.settings.window.y
        if saved_x is not None and saved_y is not None:
            self.move(saved_x, saved_y)
            return

        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        self.move(available.right() - self.width() - 19, available.top() + 60)

    def _resize_edges_at(self, position: QPoint) -> Qt.Edges:
        edges = Qt.Edges()
        if position.x() < self.RESIZE_MARGIN:
            edges |= Qt.Edge.LeftEdge
        elif position.x() >= self.width() - self.RESIZE_MARGIN:
            edges |= Qt.Edge.RightEdge
        if position.y() < self.RESIZE_MARGIN:
            edges |= Qt.Edge.TopEdge
        elif position.y() >= self.height() - self.RESIZE_MARGIN:
            edges |= Qt.Edge.BottomEdge
        return edges

    @staticmethod
    def _cursor_for_edges(edges: Qt.Edges) -> Qt.CursorShape:
        if edges in (
            Qt.Edge.LeftEdge | Qt.Edge.TopEdge,
            Qt.Edge.RightEdge | Qt.Edge.BottomEdge,
        ):
            return Qt.CursorShape.SizeFDiagCursor
        if edges in (
            Qt.Edge.RightEdge | Qt.Edge.TopEdge,
            Qt.Edge.LeftEdge | Qt.Edge.BottomEdge,
        ):
            return Qt.CursorShape.SizeBDiagCursor
        if edges & (Qt.Edge.LeftEdge | Qt.Edge.RightEdge):
            return Qt.CursorShape.SizeHorCursor
        if edges & (Qt.Edge.TopEdge | Qt.Edge.BottomEdge):
            return Qt.CursorShape.SizeVerCursor
        return Qt.CursorShape.ArrowCursor

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        self._update_resize_cursor(event.position().toPoint())
        super().mouseMoveEvent(event)

    def _refresh_cursor_from_global(self) -> None:
        position = self.mapFromGlobal(QCursor.pos())
        if self.rect().contains(position):
            self._update_resize_cursor(position)
        else:
            self.unsetCursor()

    def _update_resize_cursor(self, position: QPoint) -> None:
        self.setCursor(
            self._cursor_for_edges(self._resize_edges_at(position))
        )

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            edges = self._resize_edges_at(event.position().toPoint())
            handle = self.windowHandle()
            if edges and handle is not None and handle.startSystemResize(edges):
                event.accept()
                return
        super().mousePressEvent(event)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if self.isVisible():
            self.resize_save_timer.start()

    def moveEvent(self, event: QMoveEvent) -> None:
        super().moveEvent(event)

    def _save_window_state(self, *, position=None, size=None) -> bool:
        position = position or self.pos()
        size = size or self.size()
        self.settings.window.x = position.x()
        self.settings.window.y = position.y()
        self.settings.window.width = size.width()
        self.settings.window.height = size.height()
        self.settings.window.is_pinned = self._is_pinned
        return self.settings_service.save(self.settings)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.resize_save_timer.stop()
        self._save_window_state()
        if (
            not self._force_exit
            and self._tray_available
            and self.settings.window.close_to_tray
        ):
            event.ignore()
            self.hide()
            return
        super().closeEvent(event)
