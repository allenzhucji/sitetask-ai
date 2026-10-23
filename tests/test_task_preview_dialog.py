from __future__ import annotations

from datetime import date, time

from app.models.parsed_task import ParsedTaskResult
from app.models.task import Category, Priority
from app.ui.task_preview_dialog import TaskPreviewDialog


def test_valid_preview_starts_read_only_and_can_be_edited(qtbot):
    result = ParsedTaskResult(
        title="回复IRF-023",
        due_date=date(2026, 7, 18),
        due_time=time(15, 0),
        category=Category.IRF,
        priority=Priority.NORMAL,
        confidence=0.97,
        used_default_time=False,
    )
    dialog = TaskPreviewDialog(result)
    qtbot.addWidget(dialog)

    assert dialog.title_input.isReadOnly()
    assert dialog.source_label.text() == "Local parser"
    assert dialog.confidence_label.text() == "97%"
    assert dialog.confirm_button.isEnabled()

    dialog.enable_editing()
    dialog.title_input.setText("回复 IRF-023 revised")
    dialog.category_input.setCurrentIndex(
        dialog.category_input.findData(Category.FOLLOW_UP)
    )
    values = dialog.values()

    assert not dialog.title_input.isReadOnly()
    assert values["title"] == "回复 IRF-023 revised"
    assert values["category"] is Category.FOLLOW_UP


def test_default_time_and_low_confidence_warnings_are_visible(qtbot):
    result = ParsedTaskResult(
        title="回复邮件",
        due_date=None,
        due_time=None,
        category=Category.EMAIL,
        priority=Priority.NORMAL,
        confidence=0.4,
        needs_confirmation=True,
        ambiguity_reason="No supported date expression was found.",
        used_default_time=True,
    )
    dialog = TaskPreviewDialog(result)
    qtbot.addWidget(dialog)
    dialog.show()

    assert not dialog.title_input.isReadOnly()
    assert dialog.default_time_label.isVisible()
    assert "Low confidence" in dialog.warning_label.text()
    assert "No supported date" in dialog.warning_label.text()
    assert not dialog.confirm_button.isEnabled()

    dialog.due_date_input.setText("2026-07-18")
    assert dialog.confirm_button.isEnabled()


def test_missing_action_title_must_be_entered_before_confirmation(qtbot):
    result = ParsedTaskResult(
        title="明天下午3点",
        due_date=date(2026, 7, 18),
        due_time=time(15, 0),
        confidence=0.45,
        needs_confirmation=True,
        ambiguity_reason="No actionable task title was found.",
    )
    dialog = TaskPreviewDialog(result)
    qtbot.addWidget(dialog)

    assert dialog.title_input.text() == ""
    assert not dialog.confirm_button.isEnabled()
    dialog.title_input.setText("联系顾问")
    assert dialog.confirm_button.isEnabled()
