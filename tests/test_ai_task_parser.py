from __future__ import annotations

import json
from datetime import date, datetime, time
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app.models.parsed_task import AIParsedTask
from app.models.task import Category, Priority
from app.services.ai_task_parser import (
    AI_SYSTEM_PROMPT,
    AIParseError,
    AIResponseParser,
    AIResponseValidationError,
    OpenAITaskParser,
)


VALID_PAYLOAD = {
    "title": "Renew the site access permit",
    "description": None,
    "due_date": "2026-10-01",
    "due_time": "17:00",
    "category": "Follow-up",
    "priority": "normal",
    "confidence": 0.93,
    "needs_confirmation": False,
    "ambiguity_reason": None,
}


def test_valid_far_future_response_is_preserved_and_converted():
    parser = AIResponseParser()

    ai_task = parser.parse(VALID_PAYLOAD)
    result = parser.to_parsed_task_result(ai_task)

    assert ai_task.due_date == date(2026, 10, 1)
    assert ai_task.due_time == time(17, 0)
    assert result.due_date == date(2026, 10, 1)
    assert result.category is Category.FOLLOW_UP
    assert result.priority is Priority.NORMAL
    assert result.parser_source == "ai"
    assert not result.needs_confirmation


def test_json_response_is_accepted_and_title_is_normalized():
    payload = {**VALID_PAYLOAD, "title": "  Submit annual report  "}

    parsed = AIResponseParser().parse(json.dumps(payload))

    assert parsed.title == "Submit annual report"


def test_null_date_forces_confirmation_without_inventing_date():
    payload = {
        **VALID_PAYLOAD,
        "due_date": None,
        "due_time": None,
        "needs_confirmation": False,
        "ambiguity_reason": None,
    }

    parsed = AIResponseParser().parse(payload)

    assert parsed.due_date is None
    assert parsed.needs_confirmation
    assert parsed.ambiguity_reason == (
        "AI response did not include a supported due date."
    )


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_confidence_must_be_between_zero_and_one(confidence):
    with pytest.raises(AIResponseValidationError):
        AIResponseParser().parse({**VALID_PAYLOAD, "confidence": confidence})


@pytest.mark.parametrize(
    "change",
    [
        {"category": "Construction"},
        {"priority": "critical"},
        {"due_date": "not-a-date"},
        {"due_time": "25:00"},
        {"title": "   "},
        {"unexpected": "field"},
    ],
)
def test_invalid_structured_fields_are_rejected(change):
    with pytest.raises(AIResponseValidationError):
        AIResponseParser().parse({**VALID_PAYLOAD, **change})


@pytest.mark.parametrize("payload", ["not json", "[]", "null", "42"])
def test_non_object_or_malformed_responses_are_rejected(payload):
    with pytest.raises(AIResponseValidationError) as captured:
        AIResponseParser().parse(payload)
    assert str(captured.value) == AIResponseParser.ERROR_MESSAGE


def test_validation_error_never_echoes_raw_response():
    sensitive_marker = "private-task-text-that-must-not-be-echoed"
    payload = {**VALID_PAYLOAD, "title": "", "description": sensitive_marker}

    with pytest.raises(AIResponseValidationError) as captured:
        AIResponseParser().parse(payload)

    assert sensitive_marker not in str(captured.value)
    assert sensitive_marker not in repr(captured.value)


def test_schema_requires_nullable_date_and_time_fields():
    missing_date = {key: value for key, value in VALID_PAYLOAD.items() if key != "due_date"}
    missing_time = {key: value for key, value in VALID_PAYLOAD.items() if key != "due_time"}

    with pytest.raises(AIResponseValidationError):
        AIResponseParser().parse(missing_date)
    with pytest.raises(AIResponseValidationError):
        AIResponseParser().parse(missing_time)


def test_existing_validated_model_can_be_reused():
    model = AIParsedTask.model_validate(VALID_PAYLOAD)
    assert AIResponseParser().parse(model) is model


class FakeResponses:
    def __init__(self, output_parsed):
        self.output_parsed = output_parsed
        self.calls = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(output_parsed=self.output_parsed)


class FakeClient:
    def __init__(self, output_parsed):
        self.responses = FakeResponses(output_parsed)


class FakeModels:
    def __init__(self, *, fails: bool = False):
        self.fails = fails
        self.calls = []

    def retrieve(self, model: str):
        self.calls.append(model)
        if self.fails:
            raise RuntimeError("private provider error")
        return SimpleNamespace(id=model)


class FakeConnectionClient:
    def __init__(self, *, fails: bool = False):
        self.models = FakeModels(fails=fails)


def test_openai_parser_uses_structured_response_and_runtime_context():
    ai_task = AIParsedTask.model_validate(VALID_PAYLOAD)
    client = FakeClient(ai_task)
    received_keys = []
    parser = OpenAITaskParser(
        client_factory=lambda *, api_key: received_keys.append(api_key) or client
    )

    result = parser.parse(
        "On 1 October renew the site access permit",
        api_key="sk-test-secret",
        model="test-structured-model",
        now=datetime(2026, 7, 17, 14, 30, tzinfo=ZoneInfo("Asia/Dubai")),
        default_due_time="17:00",
        apply_default_time=True,
    )

    assert result.parser_source == "ai"
    assert result.due_date == date(2026, 10, 1)
    assert received_keys == ["sk-test-secret"]
    call = client.responses.calls[0]
    assert call["model"] == "test-structured-model"
    assert call["text_format"] is AIParsedTask
    assert call["input"][0] == {"role": "system", "content": AI_SYSTEM_PROMPT}
    context = call["input"][1]["content"]
    assert "Current local date: 2026-07-17" in context
    assert "Current local time: 14:30:00" in context
    assert "System timezone: Asia/Dubai" in context
    assert "Allowed categories: Site Inspection, IRF, EFI" in context
    assert "Apply default due time: true" in context
    assert "Default due time: 17:00" in context
    assert "On 1 October renew the site access permit" in context


def test_ai_system_prompt_contains_required_far_date_and_ambiguity_rules():
    assert "Do not invent a due date or due time." in AI_SYSTEM_PROMPT
    assert "A date beyond the next three days is valid." in AI_SYSTEM_PROMPT
    assert "Do not move a future task into the next three days." in AI_SYSTEM_PROMPT
    assert "return null and set needs_confirmation to true" in AI_SYSTEM_PROMPT
    assert "Preserve IRF numbers, EFI numbers, drawing numbers" in AI_SYSTEM_PROMPT


def test_openai_parser_handles_missing_structured_output_safely():
    parser = OpenAITaskParser(
        client_factory=lambda *, api_key: FakeClient(None)
    )

    with pytest.raises(AIParseError) as captured:
        parser.parse(
            "private site task text",
            api_key="sk-private-key",
            model="test-model",
            now=datetime(2026, 7, 17, tzinfo=ZoneInfo("Asia/Dubai")),
            default_due_time="17:00",
            apply_default_time=True,
        )

    assert str(captured.value) == OpenAITaskParser.ERROR_MESSAGE
    assert "private site task text" not in repr(captured.value)
    assert "sk-private-key" not in repr(captured.value)


def test_openai_parser_does_not_create_client_without_configuration():
    calls = []
    parser = OpenAITaskParser(
        client_factory=lambda **kwargs: calls.append(kwargs)
    )
    now = datetime(2026, 7, 17, tzinfo=ZoneInfo("Asia/Dubai"))

    with pytest.raises(AIParseError):
        parser.parse(
            "Tomorrow submit report",
            api_key="",
            model="test-model",
            now=now,
            default_due_time="17:00",
            apply_default_time=True,
        )
    with pytest.raises(AIParseError):
        parser.parse(
            "Tomorrow submit report",
            api_key="sk-test",
            model="",
            now=now,
            default_due_time="17:00",
            apply_default_time=True,
        )

    assert calls == []


def test_connection_retrieves_configured_model_without_generation_request():
    client = FakeConnectionClient()
    received_keys = []
    parser = OpenAITaskParser(
        client_factory=lambda *, api_key: received_keys.append(api_key) or client
    )

    parser.test_connection(api_key="sk-test", model=" configured-model ")

    assert received_keys == ["sk-test"]
    assert client.models.calls == ["configured-model"]


def test_connection_failure_is_sanitized():
    parser = OpenAITaskParser(
        client_factory=lambda *, api_key: FakeConnectionClient(fails=True)
    )

    with pytest.raises(AIParseError) as captured:
        parser.test_connection(api_key="sk-private", model="private-model")

    assert str(captured.value) == OpenAITaskParser.CONNECTION_ERROR_MESSAGE
    assert "sk-private" not in repr(captured.value)
    assert "private provider error" not in repr(captured.value)
