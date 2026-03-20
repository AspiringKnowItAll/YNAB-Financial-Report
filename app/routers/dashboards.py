"""
Dashboard HTML routes — Phase 14.

Serves the dashboard list, view, creation, and edit pages.  The left dock
(all-dashboards sidebar) is populated on every dashboard page by passing
``all_dashboards`` in the template context.
"""

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.account import Account
from app.models.budget import Category, CategoryGroup
from app.models.dashboard import Dashboard, DashboardWidget
from app.models.import_data import ExternalAccount
from app.models.report import SyncLog
from app.models.settings import AppSettings
from app.services.settings_service import get_global_custom_css
from app.templates_config import templates

logger = logging.getLogger(__name__)

router = APIRouter(tags=["dashboards"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_all_dashboards(db: AsyncSession) -> list[Dashboard]:
    """Fetch all dashboards ordered by name."""
    result = await db.execute(select(Dashboard).order_by(Dashboard.name))
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/", response_class=HTMLResponse)
async def root_redirect(request: Request, db: AsyncSession = Depends(get_db)):
    """Redirect ``/`` to the default dashboard, or ``/dashboards/new`` if none exist."""
    # Try to find the default dashboard
    result = await db.execute(
        select(Dashboard).where(Dashboard.is_default.is_(True)).limit(1)
    )
    default = result.scalar_one_or_none()
    if default:
        return RedirectResponse(f"/dashboards/{default.id}", status_code=302)

    # Fall back to the first dashboard by ID
    result = await db.execute(select(Dashboard).order_by(Dashboard.id).limit(1))
    first = result.scalar_one_or_none()
    if first:
        return RedirectResponse(f"/dashboards/{first.id}", status_code=302)

    # No dashboards at all — go to creation form
    return RedirectResponse("/dashboards/new", status_code=302)


@router.get("/dashboards", response_class=HTMLResponse)
async def dashboard_list(request: Request, db: AsyncSession = Depends(get_db)):
    """List all dashboards."""
    all_dashboards = await _get_all_dashboards(db)
    global_custom_css = await get_global_custom_css(db, request.app.state.master_key)

    # Count widgets per dashboard in a single query
    wc_result = await db.execute(
        select(DashboardWidget.dashboard_id, func.count(DashboardWidget.id))
        .group_by(DashboardWidget.dashboard_id)
    )
    widget_counts: dict[int, int] = {row[0]: row[1] for row in wc_result.all()}

    return templates.TemplateResponse(request, "dashboards/dashboard_list.html", {
        "all_dashboards": all_dashboards,
        "widget_counts": widget_counts,
        "global_custom_css": global_custom_css,
        "current_page": "dashboard",
    })


@router.get("/dashboards/new", response_class=HTMLResponse)
async def dashboard_new(request: Request, db: AsyncSession = Depends(get_db)):
    """Render the create-dashboard form."""
    all_dashboards = await _get_all_dashboards(db)
    global_custom_css = await get_global_custom_css(db, request.app.state.master_key)

    return templates.TemplateResponse(request, "dashboards/dashboard_new.html", {
        "all_dashboards": all_dashboards,
        "global_custom_css": global_custom_css,
        "current_page": "dashboard",
    })


@router.get("/dashboards/{dashboard_id}/edit", response_class=HTMLResponse)
async def dashboard_edit(
    request: Request,
    dashboard_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Render the dashboard builder (edit mode)."""
    # Fetch the requested dashboard
    result = await db.execute(
        select(Dashboard).where(Dashboard.id == dashboard_id)
    )
    dashboard = result.scalar_one_or_none()
    if dashboard is None:
        raise HTTPException(status_code=404, detail="Dashboard not found")

    # Fetch widgets for this dashboard, ordered by position
    result = await db.execute(
        select(DashboardWidget)
        .where(DashboardWidget.dashboard_id == dashboard_id)
        .order_by(DashboardWidget.grid_y, DashboardWidget.grid_x)
    )
    widgets = list(result.scalars().all())

    # Fetch YNAB accounts (not deleted, not closed)
    result = await db.execute(
        select(Account)
        .where(Account.deleted.is_(False), Account.closed.is_(False))
        .order_by(Account.name)
    )
    ynab_accounts = list(result.scalars().all())

    # Fetch categories with group name
    result = await db.execute(
        select(Category, CategoryGroup.name)
        .join(CategoryGroup, Category.group_id == CategoryGroup.id)
        .where(
            Category.deleted.is_(False),
            Category.hidden.is_(False),
            CategoryGroup.deleted.is_(False),
            CategoryGroup.hidden.is_(False),
        )
        .order_by(CategoryGroup.name, Category.name)
    )
    categories_with_group = [
        {"id": cat.id, "name": cat.name, "group_name": group_name,
         "display_name": f"{group_name}: {cat.name}"}
        for cat, group_name in result.all()
    ]

    # Fetch active external accounts
    result = await db.execute(
        select(ExternalAccount)
        .where(ExternalAccount.is_active.is_(True))
        .order_by(ExternalAccount.name)
    )
    external_accounts = list(result.scalars().all())

    all_dashboards = await _get_all_dashboards(db)
    global_custom_css = await get_global_custom_css(db, request.app.state.master_key)

    # Serialize account/category data to JSON for JS consumption
    ynab_accounts_json = json.dumps([
        {"id": a.id, "name": a.name} for a in ynab_accounts
    ])
    external_accounts_json = json.dumps([
        {"id": a.id, "name": a.name} for a in external_accounts
    ])
    categories_json = json.dumps(categories_with_group)

    return templates.TemplateResponse(request, "dashboards/dashboard_edit.html", {
        "dashboard": dashboard,
        "widgets": widgets,
        "all_dashboards": all_dashboards,
        "global_custom_css": global_custom_css,
        "ynab_accounts_json": ynab_accounts_json,
        "external_accounts_json": external_accounts_json,
        "categories_json": categories_json,
        "current_page": "dashboard",
    })


@router.get("/dashboards/{dashboard_id}", response_class=HTMLResponse)
async def dashboard_view(
    request: Request,
    dashboard_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Render a single dashboard with its widgets."""
    # Fetch the requested dashboard
    result = await db.execute(
        select(Dashboard).where(Dashboard.id == dashboard_id)
    )
    dashboard = result.scalar_one_or_none()
    if dashboard is None:
        raise HTTPException(status_code=404, detail="Dashboard not found")

    # Fetch widgets for this dashboard, ordered by position
    result = await db.execute(
        select(DashboardWidget)
        .where(DashboardWidget.dashboard_id == dashboard_id)
        .order_by(DashboardWidget.grid_y, DashboardWidget.grid_x)
    )
    widgets = list(result.scalars().all())

    all_dashboards = await _get_all_dashboards(db)
    global_custom_css = await get_global_custom_css(db, request.app.state.master_key)

    # Fetch the most recent sync log entry scoped to the active budget
    last_sync = None
    settings_result = await db.execute(
        select(AppSettings).where(AppSettings.id == 1)
    )
    app_settings = settings_result.scalar_one_or_none()
    if app_settings and app_settings.ynab_budget_id:
        sync_result = await db.execute(
            select(SyncLog)
            .where(SyncLog.budget_id == app_settings.ynab_budget_id)
            .order_by(SyncLog.id.desc())
            .limit(1)
        )
        last_sync = sync_result.scalar_one_or_none()

    return templates.TemplateResponse(request, "dashboards/dashboard_view.html", {
        "dashboard": dashboard,
        "widgets": widgets,
        "all_dashboards": all_dashboards,
        "global_custom_css": global_custom_css,
        "last_sync": last_sync,
        "current_page": "dashboard",
    })
