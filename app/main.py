from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.database import create_all
from app.scheduler import start_scheduler, stop_scheduler


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Startup
    await create_all()
    start_scheduler()
    app.state.master_key = None  # Locked until user enters master password
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

# Static files & templates
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

# Register custom Jinja2 filter: milliunits → display dollars
def milliunit_to_dollars(value: int) -> str:
    """Convert YNAB milliunits (int) to a formatted dollar string."""
    dollars = value / 1000
    return f"${dollars:,.2f}"

templates.env.filters["milliunit_to_dollars"] = milliunit_to_dollars


# ---------------------------------------------------------------------------
# Routers (registered in Phase 2+)
# ---------------------------------------------------------------------------

# from app.routers import auth, dashboard, settings, setup, reports, api, export
# app.include_router(auth.router)
# app.include_router(dashboard.router)
# app.include_router(settings.router)
# app.include_router(setup.router)
# app.include_router(reports.router)
# app.include_router(api.router)
# app.include_router(export.router)


# ---------------------------------------------------------------------------
# Middleware — auth / setup gate
# ---------------------------------------------------------------------------

EXEMPT_PREFIXES = ("/health", "/first-run", "/unlock", "/recovery", "/static")


@app.middleware("http")
async def auth_gate(request: Request, call_next):
    path = request.url.path

    # Always allow exempt routes
    if any(path.startswith(prefix) for prefix in EXEMPT_PREFIXES):
        return await call_next(request)

    # Step 1: Has master password been set up?
    import os
    if not os.path.exists("/data/master.salt"):
        return RedirectResponse("/first-run")

    # Step 2: Is the app unlocked?
    if request.app.state.master_key is None:
        return RedirectResponse("/unlock")

    # Steps 3–4 (settings_complete, setup_complete) checked in Phase 2+
    # once the DB models and session are available.

    return await call_next(request)


# ---------------------------------------------------------------------------
# Health check (always accessible)
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok"}
