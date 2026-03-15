from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import config

scheduler = AsyncIOScheduler()


async def _run_monthly_sync() -> None:
    """Trigger the monthly YNAB sync and report generation job."""
    # Implemented in Phase 9 (Scheduler + Notion)
    raise NotImplementedError


def start_scheduler() -> None:
    """
    Start the APScheduler with a monthly CronTrigger.
    Fires on the day-of-month set by SYNC_DAY_OF_MONTH (default: 1st).
    """
    scheduler.add_job(
        _run_monthly_sync,
        CronTrigger(day=config.SYNC_DAY_OF_MONTH, hour=2, minute=0),
        id="monthly_sync",
        replace_existing=True,
    )
    scheduler.start()


def stop_scheduler() -> None:
    """Gracefully shut down the scheduler during app lifespan teardown."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
