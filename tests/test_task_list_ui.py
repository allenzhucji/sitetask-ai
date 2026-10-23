from __future__ import annotations

from datetime import date, datetime, time

from PySide6.QtCore import QRect, Qt

from app.database.connection import Database
from app.database.task_repository import TaskRepository
from app.models.task import Category, Priority, Task
from app.services.settings_service import SettingsService
from app.ui.main_widget import MainWidget
from app.ui.task_item import TaskItem
from app.utils.paths import AppPaths


TODAY = date(2026, 7, 17)
FIXED_NOW = datetime.fromisoformat("2026-07-17T08:00:00+04:00")


def add_task(
    repository: TaskRepository,
    title: str,
    due_date: date,
    *,
    due_time: time | None = None,
    category: Category = Category.OTHER,
    priority: Priority = Priority.NORMAL,
) -> Task:
    return repository.create_task(
        Task(
            title=title,
            due_date=due_date,
            due_time=due_time,
            category=category,
            priority=priority,
            created_at=FIXED_NOW,
            updated_at=FIXED_NOW,
        )
    )


def make_populated_widget(tmp_path) -> tuple[MainWidget, dict[str, Task]]:
    paths = AppPaths(tmp_path)
    repository = TaskRepository(Database(paths.database_file), clock=lambda: FIXED_NOW)
    tasks = {
        "overdue": add_task(
            repository,
            "Submit IRF-023 response",
            date(2026, 7, 16),
            due_time=time(16, 0),
            category=Category.IRF,
            priority=Priority.URGENT,
        ),
        "today": add_task(
            repository,
            "Inspect slab reinforcement",
            TODAY,
            due_time=time(9, 30),
            category=Category.SITE_INSPECTION,
        ),
        "tomorrow": add_task(
            repository,
            "Review drawing Rev. C",
            date(2026, 7, 18),
            due_time=time(10, 0),
            category=Category.DRAWING,
        ),
        "day_after": add_task(
            repository,
            "Prepare weekly report",
            date(2026, 7, 19),
            category=Category.REPORT,
        ),
        "later": add_task(
            repository,
            "Submit monthly report",
            date(2026, 8, 15),
            category=Category.REPORT,
        ),
    }
    widget = MainWidget(
        SettingsService(paths),
        repository,
        today_provider=lambda: TODAY,
    )
    return widget, tasks


def test_widget_groups_database_tasks_and_excludes_later(qtbot, tmp_path):
    widget, tasks = make_populated_widget(tmp_path)
    qtbot.addWidget(widget)
    widget.show()

    assert [section.title for section in widget.sections] == [
        "NO DUE",
        "TODAY",
        "TOMORROW",
        "DAY AFTER TOMORROW",
    ]
    displayed_ids = {
        task_item.task.id
        for section in widget.sections
        for task_item in section.task_items
    }
    assert tasks["later"].id not in displayed_ids
    assert displayed_ids == {
        tasks["overdue"].id,
        tasks["today"].id,
        tasks["tomorrow"].id,
        tasks["day_after"].id,
    }


def test_task_item_displays_title_metadata_and_priority(qtbot, tmp_path):
    widget, _ = make_populated_widget(tmp_path)
    qtbot.addWidget(widget)
    widget.show()

    overdue_item = widget.sections[0].task_items[0]
    today_item = widget.sections[1].task_items[0]
    day_after_item = widget.sections[3].task_items[0]

    assert overdue_item.title_label.text() == "Submit IRF-023 response"
    assert overdue_item.metadata_label.isHidden()
    assert overdue_item.priority_dot.isHidden()
    assert overdue_item.minimumHeight() == TaskItem.NO_DUE_HEIGHT
    # 紧急度只显示 8x8 圆点（无文字徽章），level 属性驱动 QSS 配色
    assert overdue_item.priority_dot.text() == ""
    assert overdue_item.priority_dot.property("level") == "urgent"
    assert (overdue_item.priority_dot.width(), overdue_item.priority_dot.height()) == (8, 8)
    assert today_item.metadata_label.text() == "Today · 09:30"
    assert day_after_item.metadata_label.text() == "19 Jul · All day"
    assert today_item.complete_checkbox.isEnabled()


def test_long_task_title_grows_card_without_widening_window(qtbot, tmp_path):
    paths = AppPaths(tmp_path)
    repository = TaskRepository(Database(paths.database_file), clock=lambda: FIXED_NOW)
    long_title = (
        "Inspect reinforcement at the eastern transfer slab and issue the full "
        "consultant response before the coordination meeting"
    )
    add_task(
        repository,
        long_title,
        TODAY,
        category=Category.SITE_INSPECTION,
    )
    widget = MainWidget(
        SettingsService(paths),
        repository,
        today_provider=lambda: TODAY,
    )
    qtbot.addWidget(widget)
    widget.resize(widget.MINIMUM_WIDTH, widget.MINIMUM_HEIGHT)
    widget.show()
    qtbot.wait(20)

    task_item = widget.sections[0].task_items[0]
    # 标题完整保留（不省略）；窗口宽度不随标题加宽
    assert task_item.title_label.text() == long_title
    assert widget.width() == widget.MINIMUM_WIDTH
    assert task_item.metadata_label.text().startswith("Today")
    # 长标题在可用宽内换行，卡片高度自适应增高，文字不被裁剪：
    # 标题实际高 >= 完整渲染所需高（且 > 单行行高，证明换行了）
    metrics = task_item.title_label.fontMetrics()
    needed = metrics.boundingRect(
        QRect(0, 0, max(1, task_item.title_label.width() - 2), 10_000),
        int(Qt.TextFlag.TextWordWrap),
        task_item.title_label.text(),
    ).height()
    assert task_item.title_label.height() > metrics.lineSpacing()
    assert task_item.title_label.height() >= needed, {
        "title_height": task_item.title_label.height(),
        "needed": needed,
        "title_width": task_item.title_label.width(),
    }
    # 卡片随换行增高（不再是紧凑单行高度）
    assert task_item.height() > TaskItem.COMPACT_HEIGHT + 2, {
        "item_height": task_item.height(),
    }


def test_minimum_window_shows_five_compact_tasks_without_scrolling(
    qtbot,
    tmp_path,
):
    # 不调 configure_application_style：setStyleSheet 会全量重抛残留的
    # qfluentwidgets 控件触发原生崩溃（见 conftest 排序注释），本测试
    # 目标是布局紧凑性，样式无关；布局无需全局 QSS。
    paths = AppPaths(tmp_path)
    repository = TaskRepository(Database(paths.database_file), clock=lambda: FIXED_NOW)
    due_dates = (
        date(2026, 7, 16),
        TODAY,
        TODAY,
        date(2026, 7, 18),
        date(2026, 7, 19),
    )
    for index, due_date in enumerate(due_dates):
        add_task(repository, f"Compact task {index + 1}", due_date)
    widget = MainWidget(
        SettingsService(paths),
        repository,
        today_provider=lambda: TODAY,
    )
    qtbot.addWidget(widget)
    widget.resize(widget.MINIMUM_WIDTH, widget.MINIMUM_HEIGHT)
    widget.show()
    qtbot.wait(20)

    task_items = [
        item
        for section in widget.sections
        for item in section.task_items
    ]
    assert len(task_items) == 5
    assert widget.task_scroll_area.verticalScrollBar().maximum() == 0, {
        "viewport_height": widget.task_scroll_area.viewport().height(),
        "container_height": widget.task_container.sizeHint().height(),
        "section_heights": [
            section.sizeHint().height()
            for section in widget.sections
        ],
        "task_heights": [item.height() for item in task_items],
    }
    # CardWidget 自带 1px 边框，总高 = 紧凑高 + 2；offscreen 平台字体
    # 行高（~40px）远大于真实平台（~18px），卡片高度锁定略高，留 4px 余量
    assert max(item.height() for item in task_items) <= TaskItem.COMPACT_HEIGHT + 4, {
        "heights": [item.height() for item in task_items],
    }
