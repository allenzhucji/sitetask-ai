from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Protocol

from app.models.parsed_task import ParsedTaskResult
from app.models.settings import Settings
from app.models.task import current_local_datetime
from app.services.ai_task_parser import AIParseError
from app.services.credential_service import CredentialService
from app.services.local_task_parser import LocalTaskParser


class TaskParser(Protocol):
    def parse(self, text: str) -> ParsedTaskResult: ...


class AITaskParser(Protocol):
    def parse(
        self,
        text: str,
        *,
        api_key: str,
        model: str,
        now: datetime,
        default_due_time: str,
        apply_default_time: bool,
    ) -> ParsedTaskResult: ...


class ParserRouter:
    def __init__(
        self,
        *,
        local_parser: TaskParser | None = None,
        ai_parser: AITaskParser,
        credential_service: CredentialService | None = None,
        clock: Callable[[], datetime] = current_local_datetime,
    ) -> None:
        self.local_parser = local_parser or LocalTaskParser()
        self.ai_parser = ai_parser
        self.credential_service = credential_service or CredentialService()
        self.clock = clock

    def parse(self, text: str, settings: Settings) -> ParsedTaskResult:
        local_result = self.local_parser.parse(text)
        threshold = settings.ai.local_parser_threshold
        if local_result.confidence >= threshold:
            return local_result

        if not settings.ai.enabled:
            return self._require_confirmation(
                local_result,
                "Local parser confidence is below the configured threshold.",
            )
        if not settings.ai.model.strip():
            return self._require_confirmation(
                local_result,
                "AI model is not configured.",
            )

        api_key = self.credential_service.get_api_key()
        if not api_key:
            return self._require_confirmation(
                local_result,
                "AI parsing is enabled but no API key is configured.",
            )

        try:
            return self.ai_parser.parse(
                text,
                api_key=api_key,
                model=settings.ai.model,
                now=self.clock(),
                default_due_time=settings.task_defaults.default_due_time,
                apply_default_time=settings.task_defaults.apply_default_time,
            )
        except AIParseError:
            return self._require_confirmation(
                local_result,
                "AI parsing failed; review the local result.",
            )

    @staticmethod
    def _require_confirmation(
        result: ParsedTaskResult,
        reason: str,
    ) -> ParsedTaskResult:
        ambiguity = result.ambiguity_reason
        if ambiguity and reason not in ambiguity:
            ambiguity = f"{ambiguity} {reason}"
        elif not ambiguity:
            ambiguity = reason
        return result.model_copy(
            update={
                "needs_confirmation": True,
                "ambiguity_reason": ambiguity,
            }
        )
