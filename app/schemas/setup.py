from typing import Literal

from pydantic import BaseModel, Field, field_validator


class UserProfileUpdate(BaseModel):
    """Validated input for the profile setup wizard form."""

    household_size: int = Field(ge=1, le=20)
    income_type: Literal["salary", "variable", "mixed"]
    financial_goals: str = Field(min_length=1, max_length=2000)
    housing_type: Literal["rent", "own", "other"]
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("financial_goals", mode="before")
    @classmethod
    def strip_goals(cls, v: str) -> str:
        return v.strip() if v else v

    @field_validator("notes", mode="before")
    @classmethod
    def strip_notes(cls, v: str | None) -> str | None:
        if v is None:
            return None
        stripped = v.strip()
        return stripped if stripped else None
