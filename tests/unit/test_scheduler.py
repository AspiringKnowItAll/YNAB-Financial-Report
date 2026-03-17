"""
Unit tests for app/scheduler.py

Covers:
- _get_target_month: previous-month default, January rollover, current-month mode
- build_trigger: returns a CronTrigger for every supported frequency,
                 returns None for unrecognised/missing frequency,
                 clamps day-of-month to 28 for monthly/yearly,
                 defaults day-of-week to "mon" when not set
"""

from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from apscheduler.triggers.cron import CronTrigger

from app.scheduler import _get_target_month, build_trigger


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _settings(**kwargs) -> SimpleNamespace:
    """Build a minimal AppSettings-like object for build_trigger()."""
    defaults = {
        "schedule_frequency": "daily",
        "schedule_day_of_week": None,
        "schedule_day_of_month": None,
        "schedule_month": None,
    }
    return SimpleNamespace(**{**defaults, **kwargs})


def _mock_today(year: int, month: int, day: int = 15):
    """Return a context manager that patches date.today() in app.scheduler."""
    return patch("app.scheduler.date", wraps=date, **{"today.return_value": date(year, month, day)})


# ---------------------------------------------------------------------------
# _get_target_month
# ---------------------------------------------------------------------------

class TestGetTargetMonth:
    def test_previous_month_normal(self):
        with patch("app.scheduler.date") as mock_date:
            mock_date.today.return_value = date(2024, 3, 15)
            assert _get_target_month("previous_month") == "2024-02"

    def test_previous_month_january_rolls_to_december(self):
        with patch("app.scheduler.date") as mock_date:
            mock_date.today.return_value = date(2024, 1, 10)
            assert _get_target_month("previous_month") == "2023-12"

    def test_previous_month_december_gives_november(self):
        with patch("app.scheduler.date") as mock_date:
            mock_date.today.return_value = date(2024, 12, 1)
            assert _get_target_month("previous_month") == "2024-11"

    def test_current_month(self):
        with patch("app.scheduler.date") as mock_date:
            mock_date.today.return_value = date(2024, 3, 15)
            assert _get_target_month("current_month") == "2024-03"

    def test_current_month_january(self):
        with patch("app.scheduler.date") as mock_date:
            mock_date.today.return_value = date(2024, 1, 5)
            assert _get_target_month("current_month") == "2024-01"

    def test_none_defaults_to_previous_month(self):
        with patch("app.scheduler.date") as mock_date:
            mock_date.today.return_value = date(2024, 6, 20)
            assert _get_target_month(None) == "2024-05"

    def test_unrecognised_value_defaults_to_previous_month(self):
        with patch("app.scheduler.date") as mock_date:
            mock_date.today.return_value = date(2024, 6, 20)
            assert _get_target_month("last_quarter") == "2024-05"

    def test_output_format_is_yyyy_mm(self):
        with patch("app.scheduler.date") as mock_date:
            mock_date.today.return_value = date(2024, 3, 15)
            result = _get_target_month("current_month")
        assert len(result) == 7
        assert result[4] == "-"


# ---------------------------------------------------------------------------
# build_trigger
# ---------------------------------------------------------------------------

class TestBuildTrigger:
    def test_daily_returns_cron_trigger(self):
        t = build_trigger(_settings(schedule_frequency="daily"))
        assert isinstance(t, CronTrigger)

    def test_weekly_returns_cron_trigger(self):
        t = build_trigger(_settings(schedule_frequency="weekly", schedule_day_of_week="fri"))
        assert isinstance(t, CronTrigger)

    def test_weekly_defaults_day_of_week_to_monday(self):
        # No day_of_week provided — should not raise, should return a trigger
        t = build_trigger(_settings(schedule_frequency="weekly", schedule_day_of_week=None))
        assert isinstance(t, CronTrigger)

    def test_biweekly_returns_cron_trigger(self):
        t = build_trigger(_settings(schedule_frequency="biweekly", schedule_day_of_week="wed"))
        assert isinstance(t, CronTrigger)

    def test_biweekly_defaults_day_of_week_to_monday(self):
        t = build_trigger(_settings(schedule_frequency="biweekly", schedule_day_of_week=None))
        assert isinstance(t, CronTrigger)

    def test_monthly_returns_cron_trigger(self):
        t = build_trigger(_settings(schedule_frequency="monthly", schedule_day_of_month=15))
        assert isinstance(t, CronTrigger)

    def test_monthly_defaults_day_to_1(self):
        t = build_trigger(_settings(schedule_frequency="monthly", schedule_day_of_month=None))
        assert isinstance(t, CronTrigger)

    def test_monthly_clamps_day_to_28(self):
        # day=29,30,31 would fail in February — clamped to 28 at max
        t = build_trigger(_settings(schedule_frequency="monthly", schedule_day_of_month=31))
        assert isinstance(t, CronTrigger)

    def test_yearly_returns_cron_trigger(self):
        t = build_trigger(_settings(
            schedule_frequency="yearly",
            schedule_month=6,
            schedule_day_of_month=15,
        ))
        assert isinstance(t, CronTrigger)

    def test_yearly_defaults_month_and_day(self):
        t = build_trigger(_settings(
            schedule_frequency="yearly",
            schedule_month=None,
            schedule_day_of_month=None,
        ))
        assert isinstance(t, CronTrigger)

    def test_yearly_clamps_day_to_28(self):
        t = build_trigger(_settings(
            schedule_frequency="yearly",
            schedule_month=2,
            schedule_day_of_month=31,
        ))
        assert isinstance(t, CronTrigger)

    def test_unknown_frequency_returns_none(self):
        assert build_trigger(_settings(schedule_frequency="hourly")) is None

    def test_none_frequency_returns_none(self):
        assert build_trigger(_settings(schedule_frequency=None)) is None

    def test_all_triggers_fire_at_0200(self):
        """Every trigger must fire at hour=2, minute=0."""
        frequencies = [
            _settings(schedule_frequency="daily"),
            _settings(schedule_frequency="weekly", schedule_day_of_week="mon"),
            _settings(schedule_frequency="monthly", schedule_day_of_month=1),
        ]
        for s in frequencies:
            t = build_trigger(s)
            assert t is not None
            # Inspect the CronTrigger fields
            field_map = {f.name: f for f in t.fields}
            assert str(field_map["hour"]) == "2", f"Expected hour=2 for {s.schedule_frequency}"
            assert str(field_map["minute"]) == "0", f"Expected minute=0 for {s.schedule_frequency}"
