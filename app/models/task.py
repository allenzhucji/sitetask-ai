from __future__ import annotations

from datetime import date, datetime, time
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Category(StrEnum):
    SITE_INSPECTION = "Site Inspection"
    IRF = "IRF"
    EFI = "EFI"
    DRAWING = "Drawing"
    METHOD_STATEMENT = "Method Statement"
    MATERIAL = "Material"
    EMAIL = "Email"
    MEETING = "Meeting"
    REPORT = "Report"
    FOLLOW_UP = "Follow-up"
    PERSONAL = "Personal"
    OTHER = "Other"


class Priority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class TaskStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class TaskSource(StrEnum):
    MANUAL = "manual"
    LOCAL_PARSER = "local_parser"
    AI = "ai"


def current_local_datetime() -> datetime:
    return datetime.now().astimezone()


class Task(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    title: str = Field(min_length=1)
    description: str | None = None
    due_date: date
    due_time: time | None = None
    category: Category = Category.OTHER
    priority: Priority = Priority.NORMAL
    status: TaskStatus = TaskStatus.PENDING
    source: TaskSource = TaskSource.MANUAL
    source_reference: str | None = None
    no_due: bool = False
    created_at: datetime = Field(default_factory=current_local_datetime)
    sort_order: int | None = Field(default=None, ge=0)
    updated_at: datetime = Field(default_factory=current_local_datetime)
    completed_at: datetime | None = None

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        title = value.strip()
        if not title:
            raise ValueError("Task title must not be empty")
        return title
