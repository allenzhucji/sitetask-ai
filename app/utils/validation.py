from __future__ import annotations

import re
from datetime import date, datetime, time


TIME_PATTERN = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


def normalize_task_title(value: str) -> str:
    title = value.strip()
    if not title:
        raise ValueError("任务标题不能为空。")
    return title


def parse_due_date(value: str) -> date:
    text = value.strip()
    if not text:
        raise ValueError("截止日期不能为空。")
    try:
        return date.fromisoformat(text)
    except ValueError as error:
        raise ValueError("日期格式无效，请使用 YYYY-MM-DD。") from error


def parse_optional_due_time(value: str) -> time | None:
    text = value.strip()
    if not text:
        return None
    if not TIME_PATTERN.fullmatch(text):
        raise ValueError("时间格式无效，请使用 HH:MM。")
    return datetime.strptime(text, "%H:%M").time()
