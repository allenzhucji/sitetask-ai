from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Protocol

from pydantic import ValidationError

from app.models.parsed_task import AIParsedTask, ParsedTaskResult
from app.models.task import Category


AI_SYSTEM_PROMPT = """You are a task extraction assistant for a construction site engineer.

Extract exactly one actionable task from the user's text.

Resolve relative dates using the supplied current local date,
current local time, and timezone.

Return structured data only.

Rules:

1. Do not invent a due date or due time.
2. A date beyond the next three days is valid.
3. Do not move a future task into the next three days.
4. If the date is ambiguous, return null and set needs_confirmation to true.
5. Use YYYY-MM-DD for dates.
6. Use HH:MM in 24-hour format for time.
7. Keep the title concise and actionable.
8. Remove date and time expressions from the title.
9. Preserve IRF numbers, EFI numbers, drawing numbers, revision numbers,
locations and responsible parties.
10. Category must use an allowed value.
11. Priority must be low, normal, high or urgent.
12. Return confidence from 0 to 1.
13. Explain ambiguity briefly in ambiguity_reason.
14. Never add a task not explicitly or reasonably implied."""


class ResponsesResource(Protocol):
    def parse(self, **kwargs: Any) -> Any: ...


class ModelsResource(Protocol):
    def retrieve(self, model: str, **kwargs: Any) -> Any: ...


class OpenAIClient(Protocol):
    responses: ResponsesResource
    models: ModelsResource


class AIResponseValidationError(ValueError):
    """Safe validation error that never includes the raw model response."""


class AIResponseParser:
    ERROR_MESSAGE = "AI response is not valid structured task data."

    def parse(
        self,
        payload: str | Mapping[str, Any] | AIParsedTask,
    ) -> AIParsedTask:
        if isinstance(payload, AIParsedTask):
            return payload

        data: object = payload
        if isinstance(payload, str):
            try:
                data = json.loads(payload)
            except (json.JSONDecodeError, TypeError) as error:
                raise AIResponseValidationError(self.ERROR_MESSAGE) from error

        if not isinstance(data, Mapping):
            raise AIResponseValidationError(self.ERROR_MESSAGE)
        try:
            return AIParsedTask.model_validate(dict(data))
        except (ValidationError, TypeError, ValueError) as error:
            raise AIResponseValidationError(self.ERROR_MESSAGE) from error

    def to_parsed_task_result(
        self,
        payload: str | Mapping[str, Any] | AIParsedTask,
    ) -> ParsedTaskResult:
        return self.parse(payload).to_parsed_task_result()


class AIParseError(RuntimeError):
    """Sanitized AI failure suitable for application-level fallback."""


class OpenAITaskParser:
    ERROR_MESSAGE = "AI task parsing failed. Review the task manually."
    CONNECTION_ERROR_MESSAGE = "OpenAI connection test failed."

    def __init__(self, *, client_factory: Any | None = None) -> None:
        self.client_factory = client_factory or self._create_client
        self.response_parser = AIResponseParser()

    def parse(
        self,
        text: str,
        *,
        api_key: str,
        model: str,
        now: datetime,
        default_due_time: str,
        apply_default_time: bool,
    ) -> ParsedTaskResult:
        task_text = text.strip()
        if not task_text:
            raise ValueError("Task text must not be empty")
        if not api_key.strip():
            raise AIParseError("OpenAI API key is not configured.")
        if not model.strip():
            raise AIParseError("OpenAI model is not configured.")

        local_now = now if now.tzinfo is not None else now.astimezone()
        context = self._build_context(
            task_text,
            local_now,
            default_due_time,
            apply_default_time,
        )
        try:
            client: OpenAIClient = self.client_factory(api_key=api_key)
            response = client.responses.parse(
                model=model.strip(),
                input=[
                    {"role": "system", "content": AI_SYSTEM_PROMPT},
                    {"role": "user", "content": context},
                ],
                text_format=AIParsedTask,
            )
            parsed = getattr(response, "output_parsed", None)
            if parsed is None:
                raise AIResponseValidationError(AIResponseParser.ERROR_MESSAGE)
            return self.response_parser.to_parsed_task_result(parsed)
        except Exception:
            # API, refusal and validation details may contain user text or secrets.
            raise AIParseError(self.ERROR_MESSAGE) from None

    def test_connection(self, *, api_key: str, model: str) -> None:
        if not api_key.strip():
            raise AIParseError("OpenAI API key is not configured.")
        model_name = model.strip()
        if not model_name:
            raise AIParseError("OpenAI model is not configured.")
        try:
            client: OpenAIClient = self.client_factory(api_key=api_key)
            client.models.retrieve(model_name)
        except Exception:
            raise AIParseError(self.CONNECTION_ERROR_MESSAGE) from None

    @staticmethod
    def _build_context(
        task_text: str,
        now: datetime,
        default_due_time: str,
        apply_default_time: bool,
    ) -> str:
        timezone_name = str(now.tzinfo) or "local"
        allowed_categories = ", ".join(category.value for category in Category)
        default_setting = default_due_time if apply_default_time else "disabled"
        return (
            f"Current local date: {now.date().isoformat()}\n"
            f"Current local time: {now.time().replace(microsecond=0).isoformat()}\n"
            f"System timezone: {timezone_name}\n"
            f"Allowed categories: {allowed_categories}\n"
            f"Apply default due time: {str(apply_default_time).lower()}\n"
            f"Default due time: {default_setting}\n"
            f"User original input: {task_text}"
        )

    @staticmethod
    def _create_client(*, api_key: str) -> OpenAIClient:
        from openai import OpenAI

        return OpenAI(api_key=api_key)
