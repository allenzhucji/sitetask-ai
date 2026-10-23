from __future__ import annotations

from datetime import date, datetime, timedelta

from PySide6.QtCore import QPoint, QSize, Qt

from app.database.connection import Database
from app.database.task_repository import TaskRepository
from app.models.task import Task

from app.services.settings_service import SettingsService
from app.ui.main_widget import MainWidget
from app.utils.paths import AppPaths


def make_widget(tmp_path) -> tuple[MainWidget, SettingsService]:
    service = SettingsService(AppPaths(tmp_path))
    return MainWidget(service), service


def test_edges_and_corners_have_resize_targets(qtbot, tmp_path):
    widget, _ = make_widget(tmp_path)
    qtbot.addWidget(widget)
    widget.resize(400, 700)

    assert widget._resize_edges_at(QPoint(0, 350)) == Qt.Edge.LeftEdge
    assert widget._resize_edges_at(QPoint(399, 350)) == Qt.Edge.RightEdge
    assert widget._resize_edges_at(QPoint(200, 0)) == Qt.Edge.TopEdge
    assert widget._resize_edges_at(QPoint(200, 699)) == Qt.Edge.BottomEdge
    assert widget._resize_edges_at(QPoint(0, 0)) == (
        Qt.Edge.LeftEdge | Qt.Edge.TopEdge
    )
    assert widget._resize_edges_at(QPoint(399, 699)) == (
        Qt.Edge.RightEdge | Qt.Edge.BottomEdge
    )
    assert not widget._resize_edges_at(QPoint(200, 350))


def test_minimum_window_size_is_enforced(qtbot, tmp_path):
    widget, _ = make_widget(tmp_path)
    qtbot.addWidget(widget)
    widget.resize(100, 100)

    assert widget.size() == QSize(340, 480)


def test_resized_geometry_is_saved_and_restored(qtbot, tmp_path):
    widget, service = make_widget(tmp_path)
    qtbot.addWidget(widget)
    widget.show()
    widget.resize(535, 765)

    qtbot.wait(300)

    saved = service.load()
    assert saved.window.width == 535
    assert saved.window.height == 765

    restarted = MainWidget(service)
    qtbot.addWidget(restarted)
    assert restarted.size() == QSize(535, 765)


def test_minimum_width_keeps_quick_add_controls_inside_widget(qtbot, tmp_path):
    widget, _ = make_widget(tmp_path)
    qtbot.addWidget(widget)
    widget.resize(widget.MINIMUM_WIDTH, widget.MINIMUM_HEIGHT)
    widget.show()
    widget.set_input_panel_expanded(True)
    qtbot.wait(20)

    controls = (
        widget.quick_add.date_input,
        widget.quick_add.time_input,
        widget.quick_add.all_day_checkbox,
        widget.quick_add.add_button,
        widget.quick_add.full_editor_button,
    )
    for control in controls:
        top_left = control.mapTo(widget, QPoint(0, 0))
        assert top_left.x() >= 0
        assert top_left.x() + control.width() <= widget.width()
    assert widget.quick_add.add_button.y() > widget.quick_add.date_input.y()


def test_task_inputs_are_collapsed_by_default_and_preserve_content(qtbot, tmp_path):
    widget, _ = make_widget(tmp_path)
    qtbot.addWidget(widget)
    widget.show()

    assert not widget.input_panel.isVisible()
    assert widget.input_panel_toggle_button.isVisible()
    assert widget.input_panel_toggle_button.text() == "＋ Add Task"
    assert widget.summary_label.parent() is widget.input_toggle_bar
    assert widget.summary_label.geometry().bottom() <= widget.input_toggle_bar.height()
    assert (
        widget.summary_label.geometry().right()
        < widget.input_panel_toggle_button.geometry().left()
    )

    qtbot.mouseClick(
        widget.input_panel_toggle_button,
        Qt.MouseButton.LeftButton,
    )
    widget.quick_add.title_input.setText("Preserve this task")
    widget.ai_input.text_input.setText("Tomorrow inspect slab")
    assert widget.input_panel.isVisible()

    qtbot.mouseClick(
        widget.input_panel_toggle_button,
        Qt.MouseButton.LeftButton,
    )
    assert not widget.input_panel.isVisible()
    assert widget.quick_add.title_input.text() == "Preserve this task"
    assert widget.ai_input.text_input.text() == "Tomorrow inspect slab"


def test_many_tasks_use_vertical_scrolling_without_horizontal_scroll(qtbot, tmp_path):
    paths = AppPaths(tmp_path)
    now = datetime.fromisoformat("2026-07-17T08:00:00+04:00")
    today = date(2026, 7, 17)
    repository = TaskRepository(Database(paths.database_file), clock=lambda: now)
    for index in range(12):
        repository.create_task(
            Task(
                title=f"Coordination follow-up item {index}",
                due_date=today + timedelta(days=index % 3),
                created_at=now,
                updated_at=now,
            )
        )
    widget = MainWidget(
        SettingsService(paths),
        repository,
        today_provider=lambda: today,
    )
    qtbot.addWidget(widget)
    widget.resize(widget.MINIMUM_WIDTH, widget.MINIMUM_HEIGHT)
    widget.show()
    qtbot.wait(20)

    assert widget.task_scroll_area.verticalScrollBar().maximum() > 0
    assert (
        widget.task_scroll_area.horizontalScrollBarPolicy()
        == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    )
    assert widget.task_container.width() <= widget.task_scroll_area.viewport().width()
