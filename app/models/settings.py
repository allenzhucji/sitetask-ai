from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SettingsModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class WindowSettings(SettingsModel):
    width: int = Field(default=400, ge=340)
    height: int = Field(default=700, ge=480)
    x: int | None = None
    y: int | None = None
    is_pinned: bool = False
    close_to_tray: bool = True
    # 主背景不透明度（0.4-0.95）：MainWidget.paintEvent 据此绘制磨砂背景
    background_opacity: float = Field(default=0.85, ge=0.4, le=0.95)


class DisplaySettings(SettingsModel):
    days_ahead: int = Field(default=3, ge=1)
    show_overdue: bool = True
    show_later_count: bool = True
    theme: Literal["dark"] = "dark"


class TaskDefaultSettings(SettingsModel):
    default_due_time: str = Field(default="17:00", pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    apply_default_time: bool = True
    default_priority: Literal["low", "normal", "high", "urgent"] = "normal"
    default_category: str = "Other"


class AISettings(SettingsModel):
    enabled: bool = False
    model: str = ""
    local_parser_threshold: float = Field(default=0.8, ge=0.0, le=1.0)


class NotificationSettings(SettingsModel):
    enabled: bool = True
    one_hour_before: bool = True
    at_due_time: bool = True


class StartupSettings(SettingsModel):
    start_with_windows: bool = False


class Settings(SettingsModel):
    window: WindowSettings = Field(default_factory=WindowSettings)
    display: DisplaySettings = Field(default_factory=DisplaySettings)
    task_defaults: TaskDefaultSettings = Field(default_factory=TaskDefaultSettings)
    ai: AISettings = Field(default_factory=AISettings)
    notifications: NotificationSettings = Field(default_factory=NotificationSettings)
    startup: StartupSettings = Field(default_factory=StartupSettings)
