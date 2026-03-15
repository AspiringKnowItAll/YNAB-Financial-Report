from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from app.database import AsyncSessionLocal, apply_migrations, create_all
from app.scheduler import reschedule_job, start_scheduler, stop_scheduler


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Startup
    await apply_migrations()   # Add new columns to existing tables (idempotent)
    await create_all()         # Create any tables that don't yet exist
    app.state.master_key = None  # Locked until user enters master password

    # Load persisted schedule settings (if any) and start the scheduler
    settings = None
    try:
        async with AsyncSessionLocal() as db:
            from app.models.settings import AppSettings
            result = await db.execute(select(AppSettings).where(AppSettings.id == 1))
            settings = result.scalar_one_or_none()
    except Exception:
        pass  # DB may be empty on very first run — scheduler starts with no job

    start_scheduler(app, settings)
    yield
    # Shutdown
    stop_scheduler()


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

app = FastAPI(
    title="YNAB Financial Report",
    lifespan=lifespan,
    docs_url=None,   # Disable Swagger UI in production
    redoc_url=None,
)

# Static files & templates (autoescape enabled for all HTML templates)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")
templates.env.autoescape = True  # XSS protection — auto-escape all template output

# Register custom Jinja2 filter: milliunits → display dollars
def milliunit_to_dollars(value: int) -> str:
    """Convert YNAB milliunits (int) to a formatted dollar string."""
    dollars = value / 1000
    return f"${dollars:,.2f}"

templates.env.filters["milliunit_to_dollars"] = milliunit_to_dollars


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

from app.routers import auth, dashboard, settings, setup, reports, api, export

app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(settings.router)
app.include_router(setup.router)
app.include_router(reports.router)
app.include_router(api.router)
app.include_router(export.router)


# ---------------------------------------------------------------------------
# Middleware — auth / setup gate
# ---------------------------------------------------------------------------

EXEMPT_PREFIXES = ("/health", "/first-run", "/unlock", "/recovery", "/static")


@app.middleware("http")
async def auth_gate(request: Request, call_next):
    import os
    path = request.url.path

    # Always allow exempt routes
    if any(path.startswith(prefix) for prefix in EXEMPT_PREFIXES):
        return await call_next(request)

    # Step 1: Has master password been set up?
    if not os.path.exists("/data/master.salt"):
        return RedirectResponse("/first-run", status_code=302)

    # Step 2: Is the app unlocked?
    if request.app.state.master_key is None:
        return RedirectResponse("/unlock", status_code=302)

    # Step 3: Have settings been completed?
    if path != "/settings":
        try:
            from app.models.settings import AppSettings
            async with AsyncSessionLocal() as db:
                result = await db.execute(select(AppSettings).where(AppSettings.id == 1))
                app_settings = result.scalar_one_or_none()
            if app_settings is None or not app_settings.settings_complete:
                return RedirectResponse("/settings", status_code=302)
        except Exception:
            pass  # DB not yet available on very first startup — let through

    # Step 4: Has the user profile wizard been completed?
    if path not in ("/settings", "/setup"):
        try:
            from app.models.user_profile import UserProfile
            async with AsyncSessionLocal() as db:
                result = await db.execute(select(UserProfile).where(UserProfile.id == 1))
                profile = result.scalar_one_or_none()
            if profile is None or not profile.setup_complete:
                return RedirectResponse("/setup", status_code=302)
        except Exception:
            pass

    return await call_next(request)


# ---------------------------------------------------------------------------
# Health check (always accessible)
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok"}
