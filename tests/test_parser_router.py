from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.models.parsed_task import ParsedTaskResult
from app.models.settings import AISettings, Settings, TaskDefaultSettings
from app.models.task import Category, Priority
from app.services.ai_task_parser import AIParseError
from app.services.parser_router import ParserRouter


NOW = datetime(2026, 7, 17, 14, 30, tzinfo=ZoneInfo("Asia/Dubai"))


def local_result(confidence: float = 0.75) -> ParsedTaskResult:
    return ParsedTaskResult(
        title="Submit report",
        due_date=date(2026, 7, 18),
        category=Category.REPORT,
        priority=Priority.NORMAL,
        confidence=confidence,
        parser_source="local",
    )


class FakeLocalParser:
    def __init__(self, result: ParsedTaskResult):
        self.result = result
        self.calls = []

    def parse(self, text: str) -> ParsedTaskResult:
        self.calls.append(text)
        return self.result


class FakeAIParser:
    def __init__(self, result: ParsedTaskResult | None = None, *, fails=False):
        self.result = result
        self.fails = fails
        self.calls = []

    def parse(self, text: str, **kwargs) -> ParsedTaskResult:
        self.calls.append((text, kwargs))
        if self.fails:
            raise AIParseError("safe failure")
        assert self.result is not None
        return self.result


class FakeCredentials:
    def __init__(self, api_key: str | None):
        self.api_key = api_key
        self.calls = 0

    def get_api_key(self) -> str | None:
        self.calls += 1
        return self.api_key


def settings(*, enabled=True, model="test-model", threshold=0.8) -> Settings:
    return Settings(
        ai=AISettings(
            enabled=enabled,
            model=model,
            local_parser_threshold=threshold,
        ),
        task_defaults=TaskDefaultSettings(
            default_due_time="16:30",
            apply_default_time=False,
        ),
    )


def make_router(local, ai, credentials) -> ParserRouter:
    return ParserRouter(
        local_parser=local,
        ai_parser=ai,
        credential_service=credentials,
        clock=lambda: NOW,
    )


def test_high_confidence_local_result_skips_credentials_and_ai():
    local = FakeLocalParser(local_result(0.80))
    ai = FakeAIParser()
    credentials = FakeCredentials("sk-test")

    result = make_router(local, ai, credentials).parse("Tomorrow submit report", settings())

    assert result.parser_source == "local"
    assert credentials.calls == 0
    assert ai.calls == []


def test_low_confidence_uses_ai_with_runtime_and_default_settings():
    local = FakeLocalParser(local_result())
    ai_result = ParsedTaskResult(
        title="Submit monthly report",
        due_date=date(2026, 8, 15),
        category=Category.REPORT,
        priority=Priority.NORMAL,
        confidence=0.95,
        parser_source="ai",
    )
    ai = FakeAIParser(ai_result)
    credentials = FakeCredentials("sk-test")

    result = make_router(local, ai, credentials).parse(
        "下个月15号提交月度报告",
        settings(),
    )

    assert result is ai_result
    text, arguments = ai.calls[0]
    assert text == "下个月15号提交月度报告"
    assert arguments == {
        "api_key": "sk-test",
        "model": "test-model",
        "now": NOW,
        "default_due_time": "16:30",
        "apply_default_time": False,
    }


def test_ai_disabled_returns_local_result_requiring_confirmation():
    local = FakeLocalParser(local_result())
    ai = FakeAIParser()
    credentials = FakeCredentials("sk-test")

    result = make_router(local, ai, credentials).parse(
        "Submit report sometime",
        settings(enabled=False),
    )

    assert result.parser_source == "local"
    assert result.needs_confirmation
    assert "below the configured threshold" in result.ambiguity_reason
    assert credentials.calls == 0
    assert ai.calls == []


def test_missing_model_or_key_falls_back_without_ai_call():
    for configured_settings, api_key, expected_reason in (
        (settings(model=""), "sk-test", "model is not configured"),
        (settings(), None, "no API key is configured"),
    ):
        local = FakeLocalParser(local_result())
        ai = FakeAIParser()
        credentials = FakeCredentials(api_key)

        result = make_router(local, ai, credentials).parse(
            "Submit report sometime",
            configured_settings,
        )

        assert result.needs_confirmation
        assert expected_reason in result.ambiguity_reason
        assert ai.calls == []


def test_ai_failure_preserves_local_result_and_existing_ambiguity():
    uncertain = local_result()
    uncertain.ambiguity_reason = "No explicit date was found."
    ai = FakeAIParser(fails=True)

    result = make_router(
        FakeLocalParser(uncertain),
        ai,
        FakeCredentials("sk-test"),
    ).parse("Submit report sometime", settings())

    assert result.title == uncertain.title
    assert result.due_date == uncertain.due_date
    assert result.parser_source == "local"
    assert result.needs_confirmation
    assert result.ambiguity_reason == (
        "No explicit date was found. AI parsing failed; review the local result."
    )
