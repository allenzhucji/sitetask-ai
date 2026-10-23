from __future__ import annotations

from datetime import date, datetime, time

import pytest

from app.services.local_task_parser import LocalTaskParser


NOW = datetime.fromisoformat("2026-07-17T09:30:00+04:00")


@pytest.fixture
def parser() -> LocalTaskParser:
    return LocalTaskParser(clock=lambda: NOW)


@pytest.mark.parametrize(
    ("text", "expected_date"),
    [
        ("下个月15号提交月度报告", date(2026, 8, 15)),
        ("下个月更新通行证", date(2026, 8, 17)),
        ("10月1日更新现场通行证", date(2026, 10, 1)),
        ("1月10日审核年度资料", date(2027, 1, 10)),
        ("2027年1月10日审核年度资料", date(2027, 1, 10)),
        ("2027-01-10 Review annual records", date(2027, 1, 10)),
        ("2026/08/15 Submit monthly report", date(2026, 8, 15)),
        ("On 1 October renew the site access permit", date(2026, 10, 1)),
        ("October 1 renew the site access permit", date(2026, 10, 1)),
        ("Oct 1, 2027 renew the permit", date(2027, 10, 1)),
        ("Submit the annual report on 15 January next year", date(2027, 1, 15)),
        ("Submit leap report on 29 February", date(2028, 2, 29)),
    ],
)
def test_future_and_explicit_dates_are_preserved(parser, text, expected_date):
    result = parser.parse(text)

    assert result.due_date == expected_date
    assert result.due_time == time(17, 0)
    assert result.used_default_time
    assert not result.needs_confirmation


def test_explicit_past_year_is_not_moved_to_the_future(parser):
    result = parser.parse("2025-01-10 Review archived records")

    assert result.due_date == date(2025, 1, 10)


@pytest.mark.parametrize(
    "text",
    [
        "2027-02-29 Submit report",
        "下个月32号提交报告",
        "31 February submit report",
    ],
)
def test_invalid_explicit_date_is_not_silently_corrected(parser, text):
    result = parser.parse(text)

    assert result.due_date is None
    assert result.needs_confirmation
    assert result.ambiguity_reason.startswith("Invalid date expression:")
