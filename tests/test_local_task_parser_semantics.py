from __future__ import annotations

from datetime import date, datetime

import pytest

from app.models.task import Category, Priority
from app.services.local_task_parser import LocalTaskParser


NOW = datetime.fromisoformat("2026-07-17T09:30:00+04:00")


@pytest.fixture
def parser() -> LocalTaskParser:
    return LocalTaskParser(clock=lambda: NOW)


@pytest.mark.parametrize(
    ("text", "expected_title", "expected_category"),
    [
        ("明天下午3点回复IRF-023", "回复IRF-023", Category.IRF),
        ("后天上午检查钢筋", "检查钢筋", Category.SITE_INSPECTION),
        ("Friday 4pm submit weekly report", "submit weekly report", Category.REPORT),
        ("next Monday review drawing Rev C", "review drawing Rev C", Category.DRAWING),
        ("下个月15号提交月度报告", "提交月度报告", Category.REPORT),
        ("10月1日更新现场通行证", "更新现场通行证", Category.OTHER),
        (
            "On 1 October renew the site access permit",
            "renew the site access permit",
            Category.OTHER,
        ),
        (
            "Submit the annual report on 15 January next year",
            "Submit the annual report",
            Category.REPORT,
        ),
        ("明天处理 EFI-012", "处理 EFI-012", Category.EFI),
        ("明天提交 Method Statement", "提交 Method Statement", Category.METHOD_STATEMENT),
        ("明天审核材料", "审核材料", Category.MATERIAL),
        ("明天参加会议", "参加会议", Category.MEETING),
        ("明天回复邮件", "回复邮件", Category.EMAIL),
        ("明天跟进顾问", "跟进顾问", Category.FOLLOW_UP),
        ("明天处理个人事项", "处理个人事项", Category.PERSONAL),
    ],
)
def test_title_cleanup_and_category_detection(
    parser,
    text,
    expected_title,
    expected_category,
):
    result = parser.parse(text)

    assert result.title == expected_title
    assert result.category is expected_category


@pytest.mark.parametrize("urgent_word", ["ASAP", "urgent", "immediately", "紧急", "马上"])
def test_explicit_urgent_words_suggest_urgent(parser, urgent_word):
    result = parser.parse(f"明天提交报告 {urgent_word}")
    assert result.priority is Priority.URGENT


def test_priority_uses_deadline_and_not_task_category(parser):
    soon = parser.parse("today 3pm submit report")
    later = parser.parse("today 4pm submit report")
    overdue = parser.parse("2026-07-01 submit report")
    irf = parser.parse("明天回复 IRF-023")
    efi = parser.parse("明天处理 EFI-012")
    inspection = parser.parse("明天检查钢筋")

    assert soon.priority is Priority.HIGH
    assert later.priority is Priority.NORMAL
    assert overdue.priority is Priority.URGENT
    assert irf.priority is Priority.NORMAL
    assert efi.priority is Priority.NORMAL
    assert inspection.priority is Priority.NORMAL


def test_missing_date_has_low_confidence_and_requires_confirmation(parser):
    result = parser.parse("回复 IRF-023")

    assert result.title == "回复 IRF-023"
    assert result.category is Category.IRF
    assert result.confidence < 0.65
    assert result.needs_confirmation


def test_date_and_time_without_action_requires_confirmation(parser):
    result = parser.parse("明天下午3点")

    assert result.due_date == date(2026, 7, 18)
    assert result.needs_confirmation
    assert result.ambiguity_reason == "No actionable task title was found."
    assert result.confidence < 0.65


def test_confidence_stays_in_valid_range(parser):
    results = (
        parser.parse("2027-01-10 10am submit annual report"),
        parser.parse("下个月更新通行证"),
        parser.parse("回复邮件"),
    )
    assert all(0.0 <= result.confidence <= 1.0 for result in results)
