from typing import Literal

from pydantic import AnyHttpUrl, BaseModel, EmailStr, Field, field_validator, model_validator


class YnabSettingsUpdate(BaseModel):
    """Validated input for the YNAB section of the Settings form."""

    ynab_api_key: str = Field(min_length=1, max_length=512)
    ynab_budget_id: str = Field(min_length=1, max_length=64)

    @field_validator("ynab_api_key", "ynab_budget_id", mode="before")
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        return v.strip()


class AiSettingsUpdate(BaseModel):
    """Validated input for the AI provider section of the Settings form."""

    ai_provider: Literal["anthropic", "openai", "openrouter", "ollama"]
    ai_model: str | None = Field(default=None, max_length=128)
    ai_api_key: str | None = Field(default=None, max_length=512)
    ai_base_url: AnyHttpUrl | None = None

    @field_validator("ai_api_key", mode="before")
    @classmethod
    def strip_api_key(cls, v: str | None) -> str | None:
        return v.strip() if v else None


class SmtpSettingsUpdate(BaseModel):
    """Validated input for the SMTP / email section of the Settings form."""

    email_enabled: bool = False
    smtp_host: str = Field(min_length=1, max_length=253)
    smtp_port: int = Field(ge=1, le=65535)
    smtp_username: str = Field(min_length=0, max_length=512)
    smtp_password: str | None = Field(default=None, max_length=512)
    smtp_use_tls: bool = True
    smtp_from_email: EmailStr
    report_to_email: EmailStr


class ScheduleSettingsUpdate(BaseModel):
    """Validated input for the scheduler section of the Settings form."""

    schedule_enabled: bool = False
    schedule_frequency: Literal["daily", "weekly", "biweekly", "monthly", "yearly"] | None = None
    schedule_day_of_month: int | None = Field(default=None, ge=1, le=28)
    schedule_day_of_week: Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"] | None = None
    schedule_month: int | None = Field(default=None, ge=1, le=12)
    schedule_report_target: Literal["previous_month", "current_month"] = "previous_month"
    schedule_send_email: bool = False

    @model_validator(mode="after")
    def check_required_fields(self) -> "ScheduleSettingsUpdate":
        if not self.schedule_enabled:
            return self
        if not self.schedule_frequency:
            raise ValueError("A frequency must be selected when scheduling is enabled.")
        freq = self.schedule_frequency
        if freq in ("weekly", "biweekly") and not self.schedule_day_of_week:
            raise ValueError(f"Day of week is required for {freq} schedules.")
        if freq in ("monthly", "yearly") and not self.schedule_day_of_month:
            raise ValueError(f"Day of month is required for {freq} schedules.")
        if freq == "yearly" and not self.schedule_month:
            raise ValueError("Month is required for yearly schedules.")
        return self


class NotionSettingsUpdate(BaseModel):
    """Validated input for the Notion section of the Settings form."""

    notion_enabled: bool = False
    notion_token: str | None = Field(default=None, max_length=512)
    notion_database_id: str | None = Field(default=None, max_length=64)

    @field_validator("notion_token", "notion_database_id", mode="before")
    @classmethod
    def strip_fields(cls, v: str | None) -> str | None:
        return v.strip() if v else None
