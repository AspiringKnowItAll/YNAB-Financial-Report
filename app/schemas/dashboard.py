"""Pydantic schemas for dashboard API request/response validation."""

import json
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# Valid time period values accepted by the widget service.
TimePeriod = Literal[
    "last_month",
    "last_3_months",
    "last_6_months",
    "ytd",
    "last_12_months",
    "last_18_months",
    "last_24_months",
    "all_time",
    "custom",
]


class DashboardCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=256)
    description: str | None = Field(default=None, max_length=2048)
    grid_columns: int = Field(default=12, ge=1, le=48)
    default_time_period: TimePeriod | None = None

    @field_validator("name", mode="before")
    @classmethod
    def name_not_blank(cls, v: str) -> str:
        if isinstance(v, str) and not v.strip():
            raise ValueError("name must not be blank or whitespace-only")
        return v


class DashboardUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=256)
    description: str | None = Field(default=None, max_length=2048)
    grid_columns: int | None = Field(default=None, ge=1, le=48)
    default_time_period: TimePeriod | None = None
    is_default: bool | None = None
    custom_css: str | None = None

    @field_validator("name", mode="before")
    @classmethod
    def name_not_blank(cls, v: str | None) -> str | None:
        if isinstance(v, str) and not v.strip():
            raise ValueError("name must not be blank or whitespace-only")
        return v


def _validate_config_json(v: str | None) -> str | None:
    """Validate that config_json is valid JSON."""
    if v is not None:
        try:
            json.loads(v)
        except (json.JSONDecodeError, ValueError) as exc:
            raise ValueError(f"config_json must be valid JSON: {exc}") from exc
    return v


class WidgetCreate(BaseModel):
    widget_type: str = Field(..., min_length=1, max_length=64)
    grid_x: int = Field(default=0, ge=0)
    grid_y: int = Field(default=0, ge=0)
    grid_w: int = Field(default=4, ge=1, le=48)
    grid_h: int = Field(default=3, ge=1, le=20)
    config_json: str = "{}"

    @field_validator("config_json")
    @classmethod
    def config_json_is_valid(cls, v: str) -> str:
        result = _validate_config_json(v)
        return result if result is not None else "{}"


class WidgetUpdate(BaseModel):
    widget_type: str | None = Field(default=None, min_length=1, max_length=64)
    grid_x: int | None = Field(default=None, ge=0)
    grid_y: int | None = Field(default=None, ge=0)
    grid_w: int | None = Field(default=None, ge=1, le=48)
    grid_h: int | None = Field(default=None, ge=1, le=20)
    config_json: str | None = None

    @field_validator("config_json")
    @classmethod
    def config_json_is_valid(cls, v: str | None) -> str | None:
        return _validate_config_json(v)


class LayoutItem(BaseModel):
    widget_id: int
    grid_x: int = Field(ge=0)
    grid_y: int = Field(ge=0)
    grid_w: int = Field(ge=1, le=48)
    grid_h: int = Field(ge=1, le=20)


class LayoutUpdate(BaseModel):
    items: list[LayoutItem]
