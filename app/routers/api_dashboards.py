"""
Dashboard API routes — Phase 14.

JSON endpoints for dashboard and widget CRUD, layout updates, and
per-widget data retrieval.
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.dashboard import Dashboard, DashboardWidget
from app.models.settings import AppSettings
from app.schemas.dashboard import (
    DashboardCreate,
    DashboardUpdate,
    LayoutUpdate,
    WidgetCreate,
    WidgetUpdate,
)
from app.services.widget_service import get_widget_data

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dashboards", tags=["api_dashboards"])


# ---------------------------------------------------------------------------
# Dashboard CRUD
# ---------------------------------------------------------------------------

@router.post("")
async def create_dashboard(
    payload: DashboardCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new dashboard."""
    now = datetime.now(timezone.utc).isoformat()
    dashboard = Dashboard(
        name=payload.name,
        description=payload.description,
        grid_columns=payload.grid_columns,
        default_time_period=payload.default_time_period,
        is_default=False,
        created_at=now,
        updated_at=now,
    )
    db.add(dashboard)
    await db.commit()
    await db.refresh(dashboard)
    return {"id": dashboard.id, "name": dashboard.name}


@router.put("/{dashboard_id}")
async def update_dashboard(
    dashboard_id: int,
    payload: DashboardUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update dashboard metadata."""
    result = await db.execute(
        select(Dashboard).where(Dashboard.id == dashboard_id)
    )
    dashboard = result.scalar_one_or_none()
    if dashboard is None:
        raise HTTPException(status_code=404, detail="Dashboard not found")

    now = datetime.now(timezone.utc).isoformat()

    # If setting as default, clear the flag on all other dashboards
    if payload.is_default is True:
        all_result = await db.execute(select(Dashboard))
        for d in all_result.scalars().all():
            if d.id != dashboard_id:
                d.is_default = False

    update_fields = payload.model_dump(exclude_unset=True)
    for field, value in update_fields.items():
        setattr(dashboard, field, value)
    dashboard.updated_at = now

    await db.commit()
    return {"ok": True}


@router.delete("/{dashboard_id}")
async def delete_dashboard(
    dashboard_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Delete a dashboard. Refuses if it is the only one."""
    from sqlalchemy import func
    count_result = await db.execute(select(func.count()).select_from(Dashboard))
    if (count_result.scalar() or 0) <= 1:
        raise HTTPException(status_code=400, detail="Cannot delete the only dashboard")

    result = await db.execute(select(Dashboard).where(Dashboard.id == dashboard_id))
    target = result.scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail="Dashboard not found")

    was_default = target.is_default

    # Delete associated widgets first
    widget_result = await db.execute(
        select(DashboardWidget).where(DashboardWidget.dashboard_id == dashboard_id)
    )
    for widget in widget_result.scalars().all():
        await db.delete(widget)

    await db.delete(target)
    await db.flush()

    # If the deleted dashboard was the default, promote the first remaining one
    if was_default:
        remaining = await db.execute(select(Dashboard).order_by(Dashboard.id).limit(1))
        new_default = remaining.scalar_one_or_none()
        if new_default:
            new_default.is_default = True

    await db.commit()
    return {"ok": True}


@router.put("/{dashboard_id}/default")
async def set_default_dashboard(
    dashboard_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Set a dashboard as the default, clearing the flag on all others."""
    result = await db.execute(
        select(Dashboard).where(Dashboard.id == dashboard_id)
    )
    dashboard = result.scalar_one_or_none()
    if dashboard is None:
        raise HTTPException(status_code=404, detail="Dashboard not found")

    # Clear all defaults
    all_result = await db.execute(select(Dashboard))
    for d in all_result.scalars().all():
        d.is_default = d.id == dashboard_id

    await db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Layout bulk update
# ---------------------------------------------------------------------------

@router.put("/{dashboard_id}/layout")
async def update_layout(
    dashboard_id: int,
    payload: LayoutUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Bulk-update widget positions for a dashboard."""
    # Verify dashboard exists
    result = await db.execute(
        select(Dashboard).where(Dashboard.id == dashboard_id)
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Dashboard not found")

    now = datetime.now(timezone.utc).isoformat()

    for item in payload.items:
        result = await db.execute(
            select(DashboardWidget).where(
                DashboardWidget.id == item.widget_id,
                DashboardWidget.dashboard_id == dashboard_id,
            )
        )
        widget = result.scalar_one_or_none()
        if widget is None:
            continue  # Skip unknown widgets silently
        widget.grid_x = item.grid_x
        widget.grid_y = item.grid_y
        widget.grid_w = item.grid_w
        widget.grid_h = item.grid_h
        widget.updated_at = now

    await db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Widget CRUD
# ---------------------------------------------------------------------------

@router.post("/{dashboard_id}/widgets")
async def create_widget(
    dashboard_id: int,
    payload: WidgetCreate,
    db: AsyncSession = Depends(get_db),
):
    """Add a widget to a dashboard."""
    result = await db.execute(
        select(Dashboard).where(Dashboard.id == dashboard_id)
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Dashboard not found")

    now = datetime.now(timezone.utc).isoformat()
    widget = DashboardWidget(
        dashboard_id=dashboard_id,
        widget_type=payload.widget_type,
        grid_x=payload.grid_x,
        grid_y=payload.grid_y,
        grid_w=payload.grid_w,
        grid_h=payload.grid_h,
        config_json=payload.config_json,
        created_at=now,
        updated_at=now,
    )
    db.add(widget)
    await db.commit()
    await db.refresh(widget)
    return {"id": widget.id}


@router.put("/{dashboard_id}/widgets/{widget_id}")
async def update_widget(
    dashboard_id: int,
    widget_id: int,
    payload: WidgetUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update a widget's config or position."""
    result = await db.execute(
        select(DashboardWidget).where(
            DashboardWidget.id == widget_id,
            DashboardWidget.dashboard_id == dashboard_id,
        )
    )
    widget = result.scalar_one_or_none()
    if widget is None:
        raise HTTPException(status_code=404, detail="Widget not found")

    now = datetime.now(timezone.utc).isoformat()
    update_fields = payload.model_dump(exclude_unset=True)
    for field, value in update_fields.items():
        setattr(widget, field, value)
    widget.updated_at = now

    await db.commit()
    return {"ok": True}


@router.delete("/{dashboard_id}/widgets/{widget_id}")
async def delete_widget(
    dashboard_id: int,
    widget_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Remove a widget from a dashboard."""
    result = await db.execute(
        select(DashboardWidget).where(
            DashboardWidget.id == widget_id,
            DashboardWidget.dashboard_id == dashboard_id,
        )
    )
    widget = result.scalar_one_or_none()
    if widget is None:
        raise HTTPException(status_code=404, detail="Widget not found")

    await db.delete(widget)
    await db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Widget data endpoint
# ---------------------------------------------------------------------------

@router.get("/{dashboard_id}/widgets/{widget_id}/data")
async def widget_data(
    dashboard_id: int,
    widget_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Fetch live data for a single widget."""
    result = await db.execute(
        select(DashboardWidget).where(
            DashboardWidget.id == widget_id,
            DashboardWidget.dashboard_id == dashboard_id,
        )
    )
    widget = result.scalar_one_or_none()
    if widget is None:
        raise HTTPException(status_code=404, detail="Widget not found")

    # Fetch settings for widget_service
    settings_result = await db.execute(
        select(AppSettings).where(AppSettings.id == 1)
    )
    settings = settings_result.scalar_one_or_none()

    data = await get_widget_data(widget, db, settings)
    return data
