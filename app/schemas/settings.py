from typing import Literal

from pydantic import AnyHttpUrl, BaseModel, EmailStr, Field, field_validator


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
    ai_model: str = Field(min_length=1, max_length=128)
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


class NotionSettingsUpdate(BaseModel):
    """Validated input for the Notion section of the Settings form."""

    notion_enabled: bool = False
    notion_token: str | None = Field(default=None, max_length=512)
    notion_database_id: str | None = Field(default=None, max_length=64)

    @field_validator("notion_token", "notion_database_id", mode="before")
    @classmethod
    def strip_fields(cls, v: str | None) -> str | None:
        return v.strip() if v else None
