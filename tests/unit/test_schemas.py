"""
Unit tests for all Pydantic input schemas.

These tests verify the input sanitization rules defined in AGENTS.md
at the router boundary — before any service layer is reached.

Covers:
- schemas/auth.py: MasterPasswordCreate, MasterPasswordUnlock, RecoveryCodeSubmit
- schemas/settings.py: YnabSettingsUpdate, AiSettingsUpdate, SmtpSettingsUpdate,
                       ScheduleSettingsUpdate, NotionSettingsUpdate
"""

import pytest
from pydantic import ValidationError

from app.schemas.auth import MasterPasswordCreate, MasterPasswordUnlock, RecoveryCodeSubmit
from app.schemas.settings import (
    AiSettingsUpdate,
    NotionSettingsUpdate,
    ScheduleSettingsUpdate,
    SmtpSettingsUpdate,
    YnabSettingsUpdate,
)


# ===========================================================================
# MasterPasswordCreate
# ===========================================================================

class TestMasterPasswordCreate:
    def _valid(self, **kwargs):
        defaults = {"password": "correct-horse-battery", "password_confirm": "correct-horse-battery"}
        return MasterPasswordCreate(**{**defaults, **kwargs})

    def test_valid(self):
        m = self._valid()
        assert m.password == "correct-horse-battery"

    def test_minimum_length_12(self):
        pw = "a" * 12
        m = MasterPasswordCreate(password=pw, password_confirm=pw)
        assert m.password == pw

    def test_too_short_raises(self):
        pw = "short"
        with pytest.raises(ValidationError):
            MasterPasswordCreate(password=pw, password_confirm=pw)

    def test_exactly_11_chars_raises(self):
        pw = "a" * 11
        with pytest.raises(ValidationError):
            MasterPasswordCreate(password=pw, password_confirm=pw)

    def test_max_length_1024(self):
        pw = "a" * 1024
        m = MasterPasswordCreate(password=pw, password_confirm=pw)
        assert len(m.password) == 1024

    def test_exceeds_max_length_raises(self):
        pw = "a" * 1025
        with pytest.raises(ValidationError):
            MasterPasswordCreate(password=pw, password_confirm=pw)

    def test_mismatched_passwords_raises(self):
        with pytest.raises(ValidationError, match="do not match"):
            MasterPasswordCreate(password="correct-horse-battery", password_confirm="wrong-password-xyz")

    def test_matching_passwords_passes(self):
        pw = "correct-horse-battery"
        m = MasterPasswordCreate(password=pw, password_confirm=pw)
        assert m.password == m.password_confirm


# ===========================================================================
# MasterPasswordUnlock
# ===========================================================================

class TestMasterPasswordUnlock:
    def test_valid(self):
        m = MasterPasswordUnlock(password="any-password")
        assert m.password == "any-password"

    def test_single_char_valid(self):
        m = MasterPasswordUnlock(password="x")
        assert m.password == "x"

    def test_empty_string_raises(self):
        with pytest.raises(ValidationError):
            MasterPasswordUnlock(password="")

    def test_max_length_1024(self):
        m = MasterPasswordUnlock(password="a" * 1024)
        assert len(m.password) == 1024

    def test_exceeds_max_length_raises(self):
        with pytest.raises(ValidationError):
            MasterPasswordUnlock(password="a" * 1025)


# ===========================================================================
# RecoveryCodeSubmit
# ===========================================================================

class TestRecoveryCodeSubmit:
    VALID_CODE = "A3K7B-X9PLQ-2NM4C-WZ8RT"

    def test_valid_code(self):
        m = RecoveryCodeSubmit(code=self.VALID_CODE)
        assert m.code == self.VALID_CODE

    def test_normalizes_to_uppercase(self):
        m = RecoveryCodeSubmit(code="a3k7b-x9plq-2nm4c-wz8rt")
        assert m.code == self.VALID_CODE

    def test_whitespace_padded_code_fails_length_check(self):
        # Pydantic v2 enforces max_length=23 before the strip validator runs,
        # so a padded submission (27 chars) is rejected outright.
        with pytest.raises(ValidationError):
            RecoveryCodeSubmit(code=f"  {self.VALID_CODE}  ")

    def test_too_short_raises(self):
        with pytest.raises(ValidationError):
            RecoveryCodeSubmit(code="A3K7B-X9PLQ-2NM4C")

    def test_too_long_raises(self):
        with pytest.raises(ValidationError):
            RecoveryCodeSubmit(code=self.VALID_CODE + "X")

    def test_exactly_23_chars_required(self):
        # Valid code is exactly 23 chars (5+1+5+1+5+1+5)
        assert len(self.VALID_CODE) == 23


# ===========================================================================
# YnabSettingsUpdate
# ===========================================================================

class TestYnabSettingsUpdate:
    def test_valid(self):
        m = YnabSettingsUpdate(ynab_api_key="mykey123", ynab_budget_id="budget-uuid-123")
        assert m.ynab_api_key == "mykey123"

    def test_strips_whitespace_from_api_key(self):
        m = YnabSettingsUpdate(ynab_api_key="  mykey123  ", ynab_budget_id="budget-id")
        assert m.ynab_api_key == "mykey123"

    def test_strips_whitespace_from_budget_id(self):
        m = YnabSettingsUpdate(ynab_api_key="key", ynab_budget_id="  budget-id  ")
        assert m.ynab_budget_id == "budget-id"

    def test_empty_api_key_raises(self):
        with pytest.raises(ValidationError):
            YnabSettingsUpdate(ynab_api_key="", ynab_budget_id="budget-id")

    def test_empty_budget_id_raises(self):
        with pytest.raises(ValidationError):
            YnabSettingsUpdate(ynab_api_key="key", ynab_budget_id="")

    def test_api_key_max_length_512(self):
        m = YnabSettingsUpdate(ynab_api_key="a" * 512, ynab_budget_id="budget-id")
        assert len(m.ynab_api_key) == 512

    def test_api_key_exceeds_max_raises(self):
        with pytest.raises(ValidationError):
            YnabSettingsUpdate(ynab_api_key="a" * 513, ynab_budget_id="budget-id")

    def test_budget_id_max_length_64(self):
        m = YnabSettingsUpdate(ynab_api_key="key", ynab_budget_id="a" * 64)
        assert len(m.ynab_budget_id) == 64

    def test_budget_id_exceeds_max_raises(self):
        with pytest.raises(ValidationError):
            YnabSettingsUpdate(ynab_api_key="key", ynab_budget_id="a" * 65)

    def test_whitespace_only_api_key_raises(self):
        # Strips to empty string → min_length=1 fails
        with pytest.raises(ValidationError):
            YnabSettingsUpdate(ynab_api_key="   ", ynab_budget_id="budget-id")


# ===========================================================================
# AiSettingsUpdate
# ===========================================================================

class TestAiSettingsUpdate:
    def _valid(self, **kwargs):
        defaults = {"ai_provider": "anthropic", "ai_model": "claude-sonnet-4-6", "ai_api_key": "sk-test"}
        return AiSettingsUpdate(**{**defaults, **kwargs})

    def test_valid_anthropic(self):
        m = self._valid(ai_provider="anthropic")
        assert m.ai_provider == "anthropic"

    def test_valid_openai(self):
        m = self._valid(ai_provider="openai")
        assert m.ai_provider == "openai"

    def test_valid_openrouter(self):
        m = self._valid(ai_provider="openrouter")
        assert m.ai_provider == "openrouter"

    def test_valid_ollama(self):
        m = self._valid(ai_provider="ollama", ai_api_key=None)
        assert m.ai_provider == "ollama"

    def test_invalid_provider_raises(self):
        with pytest.raises(ValidationError):
            self._valid(ai_provider="gemini")

    def test_model_name_max_128(self):
        m = self._valid(ai_model="a" * 128)
        assert len(m.ai_model) == 128

    def test_model_name_exceeds_max_raises(self):
        with pytest.raises(ValidationError):
            self._valid(ai_model="a" * 129)

    def test_empty_model_raises(self):
        with pytest.raises(ValidationError):
            self._valid(ai_model="")

    def test_api_key_optional(self):
        m = self._valid(ai_api_key=None)
        assert m.ai_api_key is None

    def test_api_key_stripped(self):
        m = self._valid(ai_api_key="  sk-test  ")
        assert m.ai_api_key == "sk-test"

    def test_api_key_max_512(self):
        m = self._valid(ai_api_key="a" * 512)
        assert len(m.ai_api_key) == 512

    def test_api_key_exceeds_max_raises(self):
        with pytest.raises(ValidationError):
            self._valid(ai_api_key="a" * 513)

    def test_valid_base_url(self):
        m = self._valid(ai_base_url="http://localhost:11434/v1")
        assert m.ai_base_url is not None

    def test_valid_https_base_url(self):
        m = self._valid(ai_base_url="https://openrouter.ai/api/v1")
        assert m.ai_base_url is not None

    def test_invalid_base_url_raises(self):
        with pytest.raises(ValidationError):
            self._valid(ai_base_url="not-a-url")

    def test_base_url_optional(self):
        m = self._valid(ai_base_url=None)
        assert m.ai_base_url is None


# ===========================================================================
# SmtpSettingsUpdate
# ===========================================================================

class TestSmtpSettingsUpdate:
    def _valid(self, **kwargs):
        defaults = {
            "smtp_host": "smtp.example.com",
            "smtp_port": 587,
            "smtp_username": "user@example.com",
            "smtp_from_email": "from@example.com",
            "report_to_email": "to@example.com",
        }
        return SmtpSettingsUpdate(**{**defaults, **kwargs})

    def test_valid(self):
        m = self._valid()
        assert m.smtp_host == "smtp.example.com"
        assert m.smtp_port == 587

    def test_email_enabled_defaults_false(self):
        m = self._valid()
        assert m.email_enabled is False

    def test_smtp_use_tls_defaults_true(self):
        m = self._valid()
        assert m.smtp_use_tls is True

    def test_port_min_1(self):
        m = self._valid(smtp_port=1)
        assert m.smtp_port == 1

    def test_port_0_raises(self):
        with pytest.raises(ValidationError):
            self._valid(smtp_port=0)

    def test_port_max_65535(self):
        m = self._valid(smtp_port=65535)
        assert m.smtp_port == 65535

    def test_port_65536_raises(self):
        with pytest.raises(ValidationError):
            self._valid(smtp_port=65536)

    def test_invalid_from_email_raises(self):
        with pytest.raises(ValidationError):
            self._valid(smtp_from_email="not-an-email")

    def test_invalid_to_email_raises(self):
        with pytest.raises(ValidationError):
            self._valid(report_to_email="not-an-email")

    def test_smtp_host_max_253(self):
        m = self._valid(smtp_host="a" * 253)
        assert len(m.smtp_host) == 253

    def test_smtp_host_exceeds_max_raises(self):
        with pytest.raises(ValidationError):
            self._valid(smtp_host="a" * 254)

    def test_smtp_host_empty_raises(self):
        with pytest.raises(ValidationError):
            self._valid(smtp_host="")

    def test_smtp_password_optional(self):
        m = self._valid(smtp_password=None)
        assert m.smtp_password is None

    def test_smtp_password_max_512(self):
        m = self._valid(smtp_password="a" * 512)
        assert len(m.smtp_password) == 512

    def test_smtp_password_exceeds_max_raises(self):
        with pytest.raises(ValidationError):
            self._valid(smtp_password="a" * 513)


# ===========================================================================
# ScheduleSettingsUpdate
# ===========================================================================

class TestScheduleSettingsUpdate:
    def test_disabled_requires_no_other_fields(self):
        m = ScheduleSettingsUpdate(schedule_enabled=False)
        assert m.schedule_enabled is False

    def test_enabled_daily_valid(self):
        m = ScheduleSettingsUpdate(schedule_enabled=True, schedule_frequency="daily")
        assert m.schedule_frequency == "daily"

    def test_enabled_weekly_requires_day_of_week(self):
        with pytest.raises(ValidationError, match="Day of week"):
            ScheduleSettingsUpdate(schedule_enabled=True, schedule_frequency="weekly")

    def test_enabled_weekly_with_day_of_week_valid(self):
        m = ScheduleSettingsUpdate(
            schedule_enabled=True,
            schedule_frequency="weekly",
            schedule_day_of_week="mon",
        )
        assert m.schedule_day_of_week == "mon"

    def test_enabled_biweekly_requires_day_of_week(self):
        with pytest.raises(ValidationError, match="Day of week"):
            ScheduleSettingsUpdate(schedule_enabled=True, schedule_frequency="biweekly")

    def test_enabled_monthly_requires_day_of_month(self):
        with pytest.raises(ValidationError, match="Day of month"):
            ScheduleSettingsUpdate(schedule_enabled=True, schedule_frequency="monthly")

    def test_enabled_monthly_with_day_of_month_valid(self):
        m = ScheduleSettingsUpdate(
            schedule_enabled=True,
            schedule_frequency="monthly",
            schedule_day_of_month=15,
        )
        assert m.schedule_day_of_month == 15

    def test_enabled_yearly_requires_day_and_month(self):
        with pytest.raises(ValidationError):
            ScheduleSettingsUpdate(schedule_enabled=True, schedule_frequency="yearly")

    def test_enabled_yearly_all_fields_valid(self):
        m = ScheduleSettingsUpdate(
            schedule_enabled=True,
            schedule_frequency="yearly",
            schedule_day_of_month=1,
            schedule_month=3,
        )
        assert m.schedule_month == 3

    def test_enabled_no_frequency_raises(self):
        with pytest.raises(ValidationError, match="frequency must be selected"):
            ScheduleSettingsUpdate(schedule_enabled=True)

    def test_invalid_frequency_raises(self):
        with pytest.raises(ValidationError):
            ScheduleSettingsUpdate(schedule_enabled=True, schedule_frequency="hourly")

    def test_day_of_month_min_1(self):
        m = ScheduleSettingsUpdate(
            schedule_enabled=True,
            schedule_frequency="monthly",
            schedule_day_of_month=1,
        )
        assert m.schedule_day_of_month == 1

    def test_day_of_month_0_raises(self):
        with pytest.raises(ValidationError):
            ScheduleSettingsUpdate(
                schedule_enabled=True,
                schedule_frequency="monthly",
                schedule_day_of_month=0,
            )

    def test_day_of_month_max_28(self):
        m = ScheduleSettingsUpdate(
            schedule_enabled=True,
            schedule_frequency="monthly",
            schedule_day_of_month=28,
        )
        assert m.schedule_day_of_month == 28

    def test_day_of_month_29_raises(self):
        with pytest.raises(ValidationError):
            ScheduleSettingsUpdate(
                schedule_enabled=True,
                schedule_frequency="monthly",
                schedule_day_of_month=29,
            )

    def test_schedule_month_min_1(self):
        m = ScheduleSettingsUpdate(
            schedule_enabled=True,
            schedule_frequency="yearly",
            schedule_day_of_month=1,
            schedule_month=1,
        )
        assert m.schedule_month == 1

    def test_schedule_month_0_raises(self):
        with pytest.raises(ValidationError):
            ScheduleSettingsUpdate(
                schedule_enabled=True,
                schedule_frequency="yearly",
                schedule_day_of_month=1,
                schedule_month=0,
            )

    def test_schedule_month_max_12(self):
        m = ScheduleSettingsUpdate(
            schedule_enabled=True,
            schedule_frequency="yearly",
            schedule_day_of_month=1,
            schedule_month=12,
        )
        assert m.schedule_month == 12

    def test_schedule_month_13_raises(self):
        with pytest.raises(ValidationError):
            ScheduleSettingsUpdate(
                schedule_enabled=True,
                schedule_frequency="yearly",
                schedule_day_of_month=1,
                schedule_month=13,
            )

    def test_report_target_defaults_previous_month(self):
        m = ScheduleSettingsUpdate(schedule_enabled=False)
        assert m.schedule_report_target == "previous_month"

    def test_invalid_report_target_raises(self):
        with pytest.raises(ValidationError):
            ScheduleSettingsUpdate(
                schedule_enabled=False,
                schedule_report_target="last_quarter",
            )

    def test_invalid_day_of_week_raises(self):
        with pytest.raises(ValidationError):
            ScheduleSettingsUpdate(
                schedule_enabled=True,
                schedule_frequency="weekly",
                schedule_day_of_week="monday",
            )

    def test_all_valid_day_of_week_values(self):
        for day in ("mon", "tue", "wed", "thu", "fri", "sat", "sun"):
            m = ScheduleSettingsUpdate(
                schedule_enabled=True,
                schedule_frequency="weekly",
                schedule_day_of_week=day,
            )
            assert m.schedule_day_of_week == day


# ===========================================================================
# NotionSettingsUpdate
# ===========================================================================

class TestNotionSettingsUpdate:
    def test_valid_disabled(self):
        m = NotionSettingsUpdate(notion_enabled=False)
        assert m.notion_enabled is False

    def test_enabled_with_fields(self):
        m = NotionSettingsUpdate(
            notion_enabled=True,
            notion_token="secret_token_abc",
            notion_database_id="db-uuid-123",
        )
        assert m.notion_token == "secret_token_abc"

    def test_strips_whitespace_from_token(self):
        m = NotionSettingsUpdate(notion_enabled=False, notion_token="  secret  ")
        assert m.notion_token == "secret"

    def test_strips_whitespace_from_database_id(self):
        m = NotionSettingsUpdate(notion_enabled=False, notion_database_id="  db-id  ")
        assert m.notion_database_id == "db-id"

    def test_token_optional(self):
        m = NotionSettingsUpdate(notion_enabled=False, notion_token=None)
        assert m.notion_token is None

    def test_database_id_optional(self):
        m = NotionSettingsUpdate(notion_enabled=False, notion_database_id=None)
        assert m.notion_database_id is None

    def test_token_max_512(self):
        m = NotionSettingsUpdate(notion_token="a" * 512)
        assert len(m.notion_token) == 512

    def test_token_exceeds_max_raises(self):
        with pytest.raises(ValidationError):
            NotionSettingsUpdate(notion_token="a" * 513)

    def test_database_id_max_64(self):
        m = NotionSettingsUpdate(notion_database_id="a" * 64)
        assert len(m.notion_database_id) == 64

    def test_database_id_exceeds_max_raises(self):
        with pytest.raises(ValidationError):
            NotionSettingsUpdate(notion_database_id="a" * 65)

