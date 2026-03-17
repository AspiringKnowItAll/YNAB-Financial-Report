from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.scheduler import start_scheduler, stop_scheduler


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Startup — DB calls (create_all, apply_migrations) are deferred to after
    # unlock because SQLCipher requires the master key before any DB access.
    app.state.master_key = None  # Locked until user enters master password
    start_scheduler(app)
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

# Static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

from app.routers import auth, dashboard, settings, reports, api, export, life_context, import_data

app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(settings.router)
app.include_router(reports.router)
app.include_router(api.router)
app.include_router(export.router)
app.include_router(life_context.router)
app.include_router(import_data.router)


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
    # API routes are exempt — they validate their own requirements and return JSON errors.
    if path != "/settings" and not path.startswith("/api/"):
        try:
            from app.models.settings import AppSettings
            async with AsyncSessionLocal() as db:
                result = await db.execute(select(AppSettings).where(AppSettings.id == 1))
                app_settings = result.scalar_one_or_none()
            if app_settings is None or not app_settings.settings_complete:
                return RedirectResponse("/settings", status_code=302)
        except Exception:
            pass  # DB not yet available on very first startup — let through

    return await call_next(request)


# ---------------------------------------------------------------------------
# Health check (always accessible)
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok"}
