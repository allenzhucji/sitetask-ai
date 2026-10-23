from __future__ import annotations

from datetime import date, time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.task import Category, Priority


class ParsedTaskResult(BaseModel):
    title: str = Field(min_length=1)
    description: str | None = None
    due_date: date | None = None
    due_time: time | None = None
    category: Category = Category.OTHER
    priority: Priority = Priority.NORMAL
    confidence: float = Field(ge=0.0, le=1.0)
    needs_confirmation: bool = False
    ambiguity_reason: str | None = None
    parser_source: Literal["local", "ai"] = "local"
    used_default_time: bool = False


AllowedCategory = Literal[
    "Site Inspection",
    "IRF",
    "EFI",
    "Drawing",
    "Method Statement",
    "Material",
    "Email",
    "Meeting",
    "Report",
    "Follow-up",
    "Personal",
    "Other",
]
AllowedPriority = Literal["low", "normal", "high", "urgent"]


class AIParsedTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1)
    description: str | None = None
    due_date: date | None
    due_time: time | None
    category: AllowedCategory
    priority: AllowedPriority
    confidence: float = Field(ge=0.0, le=1.0)
    needs_confirmation: bool
    ambiguity_reason: str | None = None

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        title = value.strip()
        if not title:
            raise ValueError("Task title must not be empty")
        return title

    @field_validator("description", "ambiguity_reason")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @model_validator(mode="after")
    def require_confirmation_without_date(self) -> "AIParsedTask":
        if self.due_date is None:
            self.needs_confirmation = True
            if self.ambiguity_reason is None:
                self.ambiguity_reason = "AI response did not include a supported due date."
        return self

    def to_parsed_task_result(self) -> ParsedTaskResult:
        return ParsedTaskResult(
            title=self.title,
            description=self.description,
            due_date=self.due_date,
            due_time=self.due_time,
            category=Category(self.category),
            priority=Priority(self.priority),
            confidence=self.confidence,
            needs_confirmation=self.needs_confirmation,
            ambiguity_reason=self.ambiguity_reason,
            parser_source="ai",
        )
