from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date, datetime, time, timedelta

from dateutil.relativedelta import relativedelta

from app.models.parsed_task import ParsedTaskResult
from app.models.task import Category, Priority, current_local_datetime


ENGLISH_WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}
CHINESE_WEEKDAYS = {
    "一": 0,
    "二": 1,
    "三": 2,
    "四": 3,
    "五": 4,
    "六": 5,
    "日": 6,
    "天": 6,
}
CHINESE_DIGITS = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
ENGLISH_MONTHS = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sep": 9,
    "sept": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}
MONTH_PATTERN = "|".join(ENGLISH_MONTHS)
CATEGORY_RULES = (
    (
        Category.IRF,
        (r"(?<![a-z0-9])irf(?![a-z0-9])", r"\binspection\s+request\b"),
    ),
    (
        Category.EFI,
        (r"(?<![a-z0-9])efi(?![a-z0-9])", r"\bfield\s+instruction\b"),
    ),
    (
        Category.DRAWING,
        (r"\bdrawing\b", r"\brevision\b", r"\brev\b", r"图纸"),
    ),
    (Category.METHOD_STATEMENT, (r"\bmethod\s+statement\b", r"施工方案")),
    (
        Category.SITE_INSPECTION,
        (r"\binspect(?:ion)?\b", r"现场检查", r"检查", r"验收"),
    ),
    (Category.REPORT, (r"\breport\b", r"日报", r"周报", r"月报", r"报告")),
    (Category.MEETING, (r"\bmeeting\b", r"会议", r"开会")),
    (Category.MATERIAL, (r"\bmaterial\b", r"材料")),
    (Category.EMAIL, (r"\bemail\b", r"\breply\b", r"\bsend\b", r"邮件", r"回复")),
    (Category.FOLLOW_UP, (r"\bfollow[ -]?up\b", r"跟进")),
    (Category.PERSONAL, (r"\bpersonal\b", r"个人")),
)
URGENT_PATTERN = re.compile(
    r"\b(?:asap|urgent|immediately)\b|紧急|马上|立即",
    re.IGNORECASE,
)
# 合法中文小时形态：单字 1-9，或"十X / X十 / X十Y"组合（如十、十二、二十、二十三）。
# 刻意排除"三六"这类多位无"十"组合，避免"下周三六点"中的"三六"被吞成无效小时。
CHINESE_HOUR = r"[一二两三四五六七八九]|[一二三四五六七八九]?十[一二三四五六七八九]?"


class LocalTaskParser:
    def __init__(
        self,
        *,
        clock: Callable[[], datetime] = current_local_datetime,
        default_due_time: str = "17:00",
        apply_default_time: bool = True,
    ) -> None:
        self.clock = clock
        self.default_due_time = time.fromisoformat(default_due_time)
        self.apply_default_time = apply_default_time

    def parse(self, text: str) -> ParsedTaskResult:
        title = text.strip()
        if not title:
            raise ValueError("Task text must not be empty")

        now = self.clock()
        if now.tzinfo is None:
            now = now.astimezone()
        explicit_time = self._parse_time(title)
        date_error: str | None = None
        try:
            due_date = self._parse_date(title, now, explicit_time)
        except ValueError as error:
            due_date = None
            date_error = str(error)
        used_default_time = (
            due_date is not None
            and explicit_time is None
            and self.apply_default_time
        )
        due_time = (
            self.default_due_time if used_default_time else explicit_time
        )

        cleaned_title = self._clean_title(title)
        title_missing = not cleaned_title
        result_title = cleaned_title or title
        category = self._suggest_category(result_title)
        priority = self._suggest_priority(title, due_date, due_time, now)

        needs_confirmation = due_date is None or title_missing
        ambiguity_reason = date_error
        if needs_confirmation and ambiguity_reason is None:
            ambiguity_reason = (
                "No supported date expression was found."
                if due_date is None
                else "No actionable task title was found."
            )
        confidence = self._confidence(
            title,
            due_date,
            explicit_time,
            category,
            title_missing,
            date_error,
        )

        return ParsedTaskResult(
            title=result_title,
            due_date=due_date,
            due_time=due_time,
            category=category,
            priority=priority,
            confidence=confidence,
            needs_confirmation=needs_confirmation,
            ambiguity_reason=ambiguity_reason,
            parser_source="local",
            used_default_time=used_default_time,
        )

    def _clean_title(self, text: str) -> str:
        chinese_number = r"[一二两三四五六七八九十]{1,3}"
        date_patterns = (
            r"(?<!\d)\d{4}[-/.]\d{1,2}[-/.]\d{1,2}(?!\d)",
            r"(?<!\d)\d{4}年\s*\d{1,2}月\s*\d{1,2}[日号]?",
            r"下个月(?:\s*\d{1,2}\s*[日号])?",
            r"(?<![\d年])\d{1,2}月\s*\d{1,2}[日号]?",
            rf"(?:\bon\s+)?\b\d{{1,2}}(?:st|nd|rd|th)?\s+"
            rf"(?:{MONTH_PATTERN})(?:\s+(?:\d{{4}}|next\s+year))?\b",
            rf"(?:\bon\s+)?\b(?:{MONTH_PATTERN})\s+"
            r"\d{1,2}(?:st|nd|rd|th)?(?:\s*,?\s*(?:\d{4}|next\s+year))?\b",
            r"\bday\s+after\s+tomorrow\b",
            r"\btomorrow\b",
            r"\btoday\b",
            r"后天|明天|今天",
            r"(?:(?:下周|下星期|本周|本星期)?(?:星期|周)[一二三四五六日天]"
            r"|下(?:周|星期)[一二三四五六日天])",
            r"(?:\bon\s+)?\b(?:next\s+)?"
            r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
        )
        time_patterns = (
            rf"(?:上午|中午|下午|晚上)\s*(?:\d{{1,2}}|{chinese_number})\s*"
            rf"(?:[点时時](?:(?:\d{{1,2}}|{chinese_number})\s*分?)?|:\d{{1,2}})",
            r"\b(?:1[0-2]|0?[1-9])(?::[0-5]\d)?\s*(?:am|pm)\b",
            r"(?<!\d)(?:[01]?\d|2[0-3]):[0-5]\d(?!\d)",
            rf"(?<![\d一二两三四五六七八九十])(?:\d{{1,2}}|{chinese_number})"
            rf"[点时時](?:(?:\d{{1,2}}|{chinese_number})\s*分?)?",
            r"上午|中午|下午|晚上",
        )
        cleaned = text
        for pattern in (*date_patterns, *time_patterns):
            cleaned = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s+", " ", cleaned)
        cleaned = re.sub(r"^[\s,;:，。·—-]+|[\s,;:，。·—-]+$", "", cleaned)
        return cleaned.strip()

    @staticmethod
    def _suggest_category(title: str) -> Category:
        for category, patterns in CATEGORY_RULES:
            if any(re.search(pattern, title, re.IGNORECASE) for pattern in patterns):
                return category
        return Category.OTHER

    @staticmethod
    def _suggest_priority(
        original_text: str,
        due_date: date | None,
        due_time: time | None,
        now: datetime,
    ) -> Priority:
        if URGENT_PATTERN.search(original_text):
            return Priority.URGENT
        if due_date is not None and due_date < now.date():
            return Priority.URGENT
        if due_date is not None and due_time is not None:
            deadline = datetime.combine(due_date, due_time, tzinfo=now.tzinfo)
            remaining = deadline - now
            if timedelta(0) <= remaining < timedelta(hours=6):
                return Priority.HIGH
        return Priority.NORMAL

    @staticmethod
    def _confidence(
        original_text: str,
        due_date: date | None,
        explicit_time: time | None,
        category: Category,
        title_missing: bool,
        date_error: str | None,
    ) -> float:
        if date_error is not None:
            return 0.2
        if due_date is None:
            return 0.4
        if re.search(r"\d{4}(?:[-/.]|年)", original_text):
            confidence = 0.95
        elif re.search(
            r"day\s+after\s+tomorrow|\btomorrow\b|\btoday\b|后天|明天|今天",
            original_text,
            re.IGNORECASE,
        ):
            confidence = 0.92
        elif re.search(r"下个月\s*$", original_text.strip()):
            confidence = 0.76
        elif "下个月" in original_text:
            confidence = 0.88
        elif re.search(
            r"(?:星期|周)[一二三四五六日天]|\b(?:next\s+)?"
            r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
            original_text,
            re.IGNORECASE,
        ):
            confidence = 0.88
        else:
            confidence = 0.86
        if explicit_time is not None:
            confidence += 0.03
        if category is not Category.OTHER:
            confidence += 0.02
        if title_missing:
            confidence = min(confidence, 0.45)
        return round(min(confidence, 0.98), 2)

    def _parse_date(
        self,
        text: str,
        now: datetime,
        explicit_time: time | None,
    ) -> date | None:
        lowered = text.casefold()
        relative_dates = (
            (r"day\s+after\s+tomorrow", 2),
            (r"\btomorrow\b", 1),
            (r"\btoday\b", 0),
            (r"后天", 2),
            (r"明天", 1),
            (r"今天", 0),
        )
        for pattern, offset in relative_dates:
            if re.search(pattern, lowered, re.IGNORECASE):
                return now.date() + timedelta(days=offset)

        future_date = self._parse_future_date(text, now.date())
        if future_date is not None:
            return future_date

        chinese_weekday = re.search(
            r"(?P<next>下周|下星期)?(?:星期|周)(?P<day>[一二三四五六日天])",
            text,
        )
        if chinese_weekday:
            target = CHINESE_WEEKDAYS[chinese_weekday.group("day")]
            force_next = chinese_weekday.group("next") is not None
            return self._resolve_weekday(now, target, explicit_time, force_next)

        english_weekday = re.search(
            r"\b(?P<next>next\s+)?(?P<day>monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
            lowered,
            re.IGNORECASE,
        )
        if english_weekday:
            target = ENGLISH_WEEKDAYS[english_weekday.group("day").casefold()]
            force_next = english_weekday.group("next") is not None
            return self._resolve_weekday(now, target, explicit_time, force_next)
        return None

    def _parse_future_date(self, text: str, today: date) -> date | None:
        numeric_date = re.search(
            r"(?<!\d)(?P<year>\d{4})[-/.](?P<month>\d{1,2})[-/.](?P<day>\d{1,2})(?!\d)",
            text,
        )
        if numeric_date:
            return self._build_date(
                int(numeric_date.group("year")),
                int(numeric_date.group("month")),
                int(numeric_date.group("day")),
                numeric_date.group(0),
            )

        chinese_full_date = re.search(
            r"(?<!\d)(?P<year>\d{4})年\s*(?P<month>\d{1,2})月\s*"
            r"(?P<day>\d{1,2})[日号]?",
            text,
        )
        if chinese_full_date:
            return self._build_date(
                int(chinese_full_date.group("year")),
                int(chinese_full_date.group("month")),
                int(chinese_full_date.group("day")),
                chinese_full_date.group(0),
            )

        next_month = re.search(
            r"下个月(?:\s*(?P<day>\d{1,2})\s*[日号])?",
            text,
        )
        if next_month:
            target_month = today + relativedelta(months=1)
            if next_month.group("day") is None:
                return target_month
            return self._build_date(
                target_month.year,
                target_month.month,
                int(next_month.group("day")),
                next_month.group(0),
            )

        chinese_month_day = re.search(
            r"(?<![\d年])(?P<month>\d{1,2})月\s*(?P<day>\d{1,2})[日号]?",
            text,
        )
        if chinese_month_day:
            return self._next_month_day(
                today,
                int(chinese_month_day.group("month")),
                int(chinese_month_day.group("day")),
                chinese_month_day.group(0),
            )

        day_month = re.search(
            rf"\b(?P<day>\d{{1,2}})(?:st|nd|rd|th)?\s+"
            rf"(?P<month>{MONTH_PATTERN})"
            r"(?:\s+(?P<year>\d{4}|next\s+year))?\b",
            text,
            re.IGNORECASE,
        )
        if day_month:
            return self._english_date_from_match(today, day_month)

        month_day = re.search(
            rf"\b(?P<month>{MONTH_PATTERN})\s+"
            r"(?P<day>\d{1,2})(?:st|nd|rd|th)?"
            r"(?:\s*,?\s*(?P<year>\d{4}|next\s+year))?\b",
            text,
            re.IGNORECASE,
        )
        if month_day:
            return self._english_date_from_match(today, month_day)
        return None

    def _english_date_from_match(self, today: date, match: re.Match[str]) -> date:
        month = ENGLISH_MONTHS[match.group("month").casefold()]
        day = int(match.group("day"))
        year_text = match.group("year")
        if year_text is None:
            return self._next_month_day(today, month, day, match.group(0))
        year = today.year + 1 if year_text.casefold().startswith("next") else int(
            year_text
        )
        return self._build_date(year, month, day, match.group(0))

    def _next_month_day(
        self,
        today: date,
        month: int,
        day: int,
        expression: str,
    ) -> date:
        for year in range(today.year, today.year + 9):
            try:
                candidate = date(year, month, day)
            except ValueError:
                continue
            if candidate >= today:
                return candidate
        raise ValueError(f"Invalid date expression: {expression}")

    @staticmethod
    def _build_date(year: int, month: int, day: int, expression: str) -> date:
        try:
            return date(year, month, day)
        except ValueError as error:
            raise ValueError(f"Invalid date expression: {expression}") from error

    @staticmethod
    def _resolve_weekday(
        now: datetime,
        target_weekday: int,
        explicit_time: time | None,
        force_next: bool,
    ) -> date:
        days_until = (target_weekday - now.weekday()) % 7
        if force_next and days_until == 0:
            days_until = 7
        elif not force_next and days_until == 0 and explicit_time is not None:
            local_now_time = now.timetz().replace(tzinfo=None)
            if explicit_time <= local_now_time:
                days_until = 7
        return now.date() + timedelta(days=days_until)

    def _parse_time(self, text: str) -> time | None:
        chinese_period = re.search(
            rf"(?P<period>上午|中午|下午|晚上)\s*"
            rf"(?P<hour>\d{{1,2}}|{CHINESE_HOUR})\s*"
            r"(?:[点时時](?:(?P<minute>\d{1,2}|[一二两三四五六七八九十]{1,3})\s*分?)?"
            r"|:(?P<colon_minute>\d{1,2}))",
            text,
        )
        if chinese_period:
            try:
                hour = self._number(chinese_period.group("hour"))
                minute_text = chinese_period.group("minute") or chinese_period.group(
                    "colon_minute"
                )
                minute = self._number(minute_text) if minute_text else 0
            except ValueError:
                hour = minute = None
            if hour is not None:
                period = chinese_period.group("period")
                if period == "上午" and hour == 12:
                    hour = 0
                elif period in {"下午", "晚上"} and hour < 12:
                    hour += 12
                elif period == "中午" and hour < 11:
                    hour += 12
                return self._valid_time(hour, minute)

        meridiem = re.search(
            r"\b(?P<hour>1[0-2]|0?[1-9])"
            r"(?::(?P<minute>[0-5]\d))?\s*"
            r"(?P<period>am|pm)\b",
            text,
            re.IGNORECASE,
        )
        if meridiem:
            hour = int(meridiem.group("hour"))
            minute = int(meridiem.group("minute") or 0)
            if meridiem.group("period").casefold() == "am":
                hour = 0 if hour == 12 else hour
            elif hour < 12:
                hour += 12
            return time(hour, minute)

        twenty_four_hour = re.search(
            r"(?<!\d)(?P<hour>[01]?\d|2[0-3]):(?P<minute>[0-5]\d)(?!\d)",
            text,
        )
        if twenty_four_hour:
            return time(
                int(twenty_four_hour.group("hour")),
                int(twenty_four_hour.group("minute")),
            )

        chinese_hour = re.compile(
            rf"(?P<hour>\d{{1,2}}|{CHINESE_HOUR})[点时時]"
            r"(?:(?P<minute>\d{1,2}|[一二两三四五六七八九十]{1,3})\s*分?)?",
        )
        for match in chinese_hour.finditer(text):
            try:
                hour = self._number(match.group("hour"))
                minute = (
                    self._number(match.group("minute"))
                    if match.group("minute")
                    else 0
                )
            except ValueError:
                # 例如"三六点"这样的非法中文数字组合，跳过并尝试下一个候选
                continue
            return self._valid_time(hour, minute)

        for period, period_time in (
            ("上午", time(9, 0)),
            ("中午", time(12, 0)),
            ("下午", time(15, 0)),
            ("晚上", time(19, 0)),
        ):
            if period in text:
                return period_time
        return None

    @staticmethod
    def _number(value: str) -> int:
        if value.isdigit():
            return int(value)
        if value == "十":
            return 10
        if "十" in value:
            tens, ones = value.split("十", maxsplit=1)
            return (CHINESE_DIGITS.get(tens, 1) * 10) + CHINESE_DIGITS.get(ones, 0)
        try:
            return CHINESE_DIGITS[value]
        except KeyError as error:
            raise ValueError(f"Unrecognized Chinese number: {value}") from error

    @staticmethod
    def _valid_time(hour: int, minute: int) -> time:
        try:
            return time(hour, minute)
        except ValueError as error:
            raise ValueError("Invalid time expression") from error
