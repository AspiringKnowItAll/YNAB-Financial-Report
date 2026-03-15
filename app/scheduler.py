"""
APScheduler integration — automated sync, report generation, and optional email delivery.

The scheduler is a module-level AsyncIOScheduler singleton started during the FastAPI
lifespan. A single job ("auto_report") is registered when scheduling is enabled in
Settings and removed when it is disabled.

Supported frequencies: daily, weekly, biweekly, monthly, yearly.
All scheduled runs fire at 02:00 container-local time.

If the app is locked when the job fires (master_key is None), the run is skipped
and the skip is logged as an error.
"""

import logging
from datetime import date

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.settings import AppSettings

logger = logging.getLogger(__name__)

_JOB_ID = "auto_report"

scheduler = AsyncIOScheduler()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_target_month(report_target: str | None) -> str:
    """Return a YYYY-MM string for the report based on the configured target."""
    today = date.today()
    if report_target == "current_month":
        return f"{today.year:04d}-{today.month:02d}"
    # Default: previous calendar month
    if today.month == 1:
        return f"{today.year - 1:04d}-12"
    return f"{today.year:04d}-{today.month - 1:02d}"


def build_trigger(settings: AppSettings) -> CronTrigger | None:
    """
    Return an APScheduler CronTrigger for the given settings, or None if the
    frequency is unrecognised or settings are incomplete.
    """
    freq = settings.schedule_frequency
    if freq == "daily":
        return CronTrigger(hour=2, minute=0)
    if freq == "weekly":
        dow = settings.schedule_day_of_week or "mon"
        return CronTrigger(day_of_week=dow, hour=2, minute=0)
    if freq == "biweekly":
        dow = settings.schedule_day_of_week or "mon"
        return CronTrigger(week="*/2", day_of_week=dow, hour=2, minute=0)
    if freq == "monthly":
        day = min(settings.schedule_day_of_month or 1, 28)
        return CronTrigger(day=day, hour=2, minute=0)
    if freq == "yearly":
        month = settings.schedule_month or 1
        day = min(settings.schedule_day_of_month or 1, 28)
        return CronTrigger(month=month, day=day, hour=2, minute=0)
    return None


# ---------------------------------------------------------------------------
# Scheduled job
# ---------------------------------------------------------------------------


async def _run_scheduled_job(app) -> None:  # app: FastAPI — avoid circular import
    """
    Execute the automated pipeline:
      1. YNAB sync
      2. Report generation (previous or current month, per settings)
      3. Email delivery (if schedule_send_email and email_enabled)

    Skips with an error log if the app is locked.
    """
    from app.models.budget import Budget
    from app.models.user_profile import UserProfile
    from app.services.email_service import build_report_email_html, send_report_email
    from app.services.encryption import decrypt
    from app.services.export_service import render_pdf
    from app.services.report_service import generate_report
    from app.services.sync_service import run_sync

    master_key = app.state.master_key
    if master_key is None:
        logger.error(
            "Scheduled job skipped: app is locked (master key not in memory). "
            "Unlock the app to resume scheduled runs."
        )
        return

    async with AsyncSessionLocal() as db:
        # Load settings
        result = await db.execute(select(AppSettings).where(AppSettings.id == 1))
        settings = result.scalar_one_or_none()

        if not settings or not settings.ynab_api_key_enc or not settings.ynab_budget_id:
            logger.error("Scheduled job skipped: YNAB API key or budget ID is not configured.")
            return

        # Load profile
        result = await db.execute(select(UserProfile).where(UserProfile.id == 1))
        profile = result.scalar_one_or_none()
        if not profile or not profile.setup_complete:
            logger.error("Scheduled job skipped: user profile is not complete.")
            return

        # 1. Sync
        try:
            api_key = decrypt(settings.ynab_api_key_enc, master_key)
            sync_log = await run_sync(db, api_key, settings.ynab_budget_id)
            logger.info(
                "Scheduled sync completed — added: %d, updated: %d.",
                sync_log.transactions_added,
                sync_log.transactions_updated,
            )
        except Exception as exc:
            logger.error("Scheduled sync failed: %s", exc)
            return

        # 2. Generate report
        target_month = _get_target_month(settings.schedule_report_target)
        try:
            snapshot = await generate_report(
                db=db,
                settings=settings,
                profile=profile,
                master_key=master_key,
                budget_id=settings.ynab_budget_id,
                month=target_month,
            )
            logger.info(
                "Scheduled report generated for %s (id=%d).", target_month, snapshot.id
            )
        except Exception as exc:
            logger.error("Scheduled report generation failed: %s", exc)
            return

        # 3. Email (optional)
        if settings.schedule_send_email and settings.email_enabled:
            try:
                result = await db.execute(
                    select(Budget).where(Budget.id == snapshot.budget_id)
                )
                budget = result.scalar_one_or_none()
                budget_name = budget.name if budget else "Your Budget"

                html_body = build_report_email_html(budget_name, snapshot)
                pdf_bytes = await render_pdf(snapshot, budget_name)
                subject = (
                    f"YNAB Financial Report \u2014 {budget_name} \u2014 {target_month}"
                )
                await send_report_email(
                    settings=settings,
                    master_key=master_key,
                    subject=subject,
                    html_body=html_body,
                    pdf_attachment=pdf_bytes,
                )
                logger.info("Scheduled report email sent for %s.", target_month)
            except Exception as exc:
                logger.error("Scheduled report email failed: %s", exc)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def reschedule_job(settings: AppSettings, app) -> None:
    """
    Remove any existing scheduled job and register a new one if scheduling is
    enabled and the settings are valid. Safe to call at any time — including
    before scheduler.start().
    """
    # Remove existing job (ignore error if it doesn't exist)
    try:
        scheduler.remove_job(_JOB_ID)
    except Exception:
        pass

    if not settings.schedule_enabled:
        logger.info("Scheduler disabled — no job registered.")
        return

    trigger = build_trigger(settings)
    if trigger is None:
        logger.warning("Scheduler enabled but frequency is unrecognised — no job registered.")
        return

    scheduler.add_job(
        _run_scheduled_job,
        trigger=trigger,
        id=_JOB_ID,
        replace_existing=True,
        args=[app],
    )
    logger.info(
        "Scheduled job registered: frequency=%s, target=%s.",
        settings.schedule_frequency,
        settings.schedule_report_target,
    )


def start_scheduler(app, settings: AppSettings | None = None) -> None:
    """
    Start the APScheduler. If settings are provided and scheduling is enabled,
    the job is registered immediately. Called once during app lifespan startup.
    """
    scheduler.start()
    if settings and settings.schedule_enabled:
        reschedule_job(settings, app)


def stop_scheduler() -> None:
    """Gracefully shut down the scheduler during app lifespan teardown."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
