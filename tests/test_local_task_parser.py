from __future__ import annotations

from datetime import date, datetime, time

import pytest

from app.services.local_task_parser import LocalTaskParser


NOW = datetime.fromisoformat("2026-07-17T09:30:00+04:00")  # Friday


@pytest.fixture
def parser() -> LocalTaskParser:
    return LocalTaskParser(clock=lambda: NOW)


@pytest.mark.parametrize(
    ("text", "expected_date", "expected_time"),
    [
        ("今天15:30回复邮件", date(2026, 7, 17), time(15, 30)),
        ("明天下午3点回复IRF-023", date(2026, 7, 18), time(15, 0)),
        ("后天上午九点检查钢筋", date(2026, 7, 19), time(9, 0)),
        ("后天上午检查钢筋", date(2026, 7, 19), time(9, 0)),
        ("明天中午开会", date(2026, 7, 18), time(12, 0)),
        ("明天下午现场检查", date(2026, 7, 18), time(15, 0)),
        ("明天晚上回复邮件", date(2026, 7, 18), time(19, 0)),
        ("today 11am send email", date(2026, 7, 17), time(11, 0)),
        ("day after tomorrow 8:15pm inspect", date(2026, 7, 19), time(20, 15)),
    ],
)
def test_relative_dates_and_times(parser, text, expected_date, expected_time):
    result = parser.parse(text)

    assert result.due_date == expected_date
    assert result.due_time == expected_time
    assert result.parser_source == "local"
    assert not result.needs_confirmation


@pytest.mark.parametrize(
    ("text", "expected_date", "expected_time"),
    [
        ("Friday 4pm submit weekly report", date(2026, 7, 17), time(16, 0)),
        ("Friday 8am submit weekly report", date(2026, 7, 24), time(8, 0)),
        ("next Monday review drawing", date(2026, 7, 20), time(17, 0)),
        ("星期一审核图纸", date(2026, 7, 20), time(17, 0)),
        ("下周一上午10点开会", date(2026, 7, 20), time(10, 0)),
    ],
)
def test_weekday_expressions_use_runtime_date_and_time(
    parser,
    text,
    expected_date,
    expected_time,
):
    result = parser.parse(text)

    assert result.due_date == expected_date
    assert result.due_time == expected_time


def test_default_time_can_be_applied_or_disabled():
    with_default = LocalTaskParser(
        clock=lambda: NOW,
        default_due_time="16:45",
        apply_default_time=True,
    ).parse("明天提交周报")
    without_default = LocalTaskParser(
        clock=lambda: NOW,
        apply_default_time=False,
    ).parse("明天提交周报")

    assert with_default.due_time == time(16, 45)
    assert with_default.used_default_time
    assert without_default.due_time is None
    assert not without_default.used_default_time


def test_missing_date_is_not_invented(parser):
    result = parser.parse("回复 IRF-023")

    assert result.due_date is None
    assert result.due_time is None
    assert result.needs_confirmation
    assert result.ambiguity_reason == "No supported date expression was found."
    assert 0.0 <= result.confidence <= 1.0


def test_empty_input_is_rejected(parser):
    with pytest.raises(ValueError, match="must not be empty"):
        parser.parse("   ")


@pytest.mark.parametrize(
    ("text", "expected_date", "expected_time"),
    [
        # 周三 + 六点："三六"连读不应崩溃或吞掉时间，应解析出"六点"
        ("下周三六点", date(2026, 7, 22), time(6, 0)),
        ("下周三 6点", date(2026, 7, 22), time(6, 0)),
        ("下周三10点", date(2026, 7, 22), time(10, 0)),
    ],
)
def test_weekday_and_chinese_time_combos(parser, text, expected_date, expected_time):
    result = parser.parse(text)

    assert result.due_date == expected_date
    assert result.due_time == expected_time
    assert result.parser_source == "local"


@pytest.mark.parametrize(
    ("text", "expected_time"),
    [
        # 合法中文时间组合保持回归（无日期表达时 due_date 为 None）
        ("六点三十六分", time(6, 36)),
        ("下午三点六分", time(15, 6)),
        ("十一点半开会", time(11, 0)),
    ],
)
def test_chinese_time_combos(parser, text, expected_time):
    result = parser.parse(text)

    assert result.due_time == expected_time
    assert result.due_date is None
    assert result.needs_confirmation


def test_invalid_chinese_number_never_crashes(parser):
    # "三六点"不是合法时间，但解析器必须优雅降级而不是抛 KeyError；
    # 可识别的"六点"仍会被提取为时间
    result = parser.parse("三六点开会")

    assert result.due_date is None
    assert result.due_time == time(6, 0)
    assert result.needs_confirmation

    result = parser.parse("下午三六点检查")
    assert result.due_time is not None


def test_pure_date_time_input_leaves_no_title_fragment(parser):
    # "下周三六点"只含日期时间，清理后标题为空 → 回退到原文并请求确认
    result = parser.parse("下周三六点")

    assert result.due_date == date(2026, 7, 22)
    assert result.due_time == time(6, 0)
    assert parser._clean_title("下周三六点") == ""
    assert result.title == "下周三六点"
    assert result.needs_confirmation
