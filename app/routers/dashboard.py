"""
Dashboard route — the app's main landing page after setup.

GET /   → Render the financial dashboard with:
  - Summary cards for the current month (income, spending, net)
  - Total net worth (sum of on-budget account balances)
  - 12-month income vs spending trend chart (Plotly)
  - Top spending categories this month vs IQR-adjusted historical average (Plotly)
  - Last sync status and trigger-sync button

Chart JSON is generated server-side and passed to the template for
client-side rendering via Plotly.js. JSON strings are HTML-safe encoded
before injection into <script> tags.
"""

import json
from collections import defaultdict
from datetime import date

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.account import Account
from app.models.budget import Budget, Category, CategoryGroup
from app.models.report import SyncLog
from app.models.settings import AppSettings
from app.models.transaction import Transaction
from app.services import analysis_service

router = APIRouter(tags=["dashboard"])
templates = Jinja2Templates(directory="app/templates")


# ---------------------------------------------------------------------------
# Plotly theme (matches base.html CSS variables)
# ---------------------------------------------------------------------------

_PLOTLY_BASE_LAYOUT: dict = {
    "paper_bgcolor": "#0f1117",
    "plot_bgcolor": "#1a1d27",
    "font": {
        "color": "#e2e4ef",
        "family": "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
        "size": 13,
    },
    "legend": {"bgcolor": "rgba(0,0,0,0)", "borderwidth": 0},
    "hoverlabel": {"bgcolor": "#1a1d27", "bordercolor": "#2e3147", "font": {"color": "#e2e4ef"}},
}

_AXIS_STYLE: dict = {"gridcolor": "#2e3147", "linecolor": "#2e3147", "zerolinecolor": "#2e3147"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_json(data: object) -> str:
    """JSON-serialize data for safe embedding in an HTML <script> tag."""
    return (
        json.dumps(data)
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )


def _last_n_months(n: int) -> list[str]:
    """Return a list of YYYY-MM strings for the last n calendar months (ascending)."""
    today = date.today()
    result = []
    year, month = today.year, today.month
    for _ in range(n):
        result.append(f"{year:04d}-{month:02d}")
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    return list(reversed(result))


def _milliunit_to_float(milliunits: int) -> float:
    return milliunits / 1000


# ---------------------------------------------------------------------------
# Dashboard route
# ---------------------------------------------------------------------------

@router.get("/", response_class=HTMLResponse)
async def get_dashboard(request: Request, db: AsyncSession = Depends(get_db)):

    # ── Settings ──────────────────────────────────────────────────────────
    result = await db.execute(select(AppSettings).where(AppSettings.id == 1))
    settings = result.scalar_one_or_none()
    budget_id: str | None = settings.ynab_budget_id if settings else None

    # ── Budget name ───────────────────────────────────────────────────────
    budget_name = "Your Budget"
    if budget_id:
        result = await db.execute(select(Budget).where(Budget.id == budget_id))
        budget = result.scalar_one_or_none()
        if budget:
            budget_name = budget.name

    # ── Last sync log ─────────────────────────────────────────────────────
    last_sync = None
    if budget_id:
        result = await db.execute(
            select(SyncLog)
            .where(SyncLog.budget_id == budget_id)
            .order_by(SyncLog.started_at.desc())
            .limit(1)
        )
        last_sync = result.scalar_one_or_none()

    # ── Account balances → net worth ──────────────────────────────────────
    net_worth: int = 0
    if budget_id:
        result = await db.execute(
            select(Account).where(
                Account.budget_id == budget_id,
                Account.deleted.is_(False),
                Account.closed.is_(False),
                Account.on_budget.is_(True),
            )
        )
        accounts = result.scalars().all()
        net_worth = sum(a.balance for a in accounts)

    # ── Transactions ──────────────────────────────────────────────────────
    transactions: list[dict] = []
    if budget_id:
        result = await db.execute(
            select(Transaction).where(
                Transaction.budget_id == budget_id,
                Transaction.deleted.is_(False),
                Transaction.approved.is_(True),
            )
        )
        transactions = [
            {
                "id": t.id,
                "date": t.date,
                "amount": t.amount,
                "category_id": t.category_id,
                "payee_name": t.payee_name,
            }
            for t in result.scalars().all()
        ]

    # ── Categories with group names ───────────────────────────────────────
    categories: list[dict] = []
    if budget_id:
        result = await db.execute(
            select(CategoryGroup).where(
                CategoryGroup.budget_id == budget_id,
                CategoryGroup.deleted.is_(False),
            )
        )
        group_map = {g.id: g.name for g in result.scalars().all()}

        result = await db.execute(
            select(Category).where(
                Category.budget_id == budget_id,
                Category.deleted.is_(False),
                Category.hidden.is_(False),
            )
        )
        categories = [
            {
                "id": c.id,
                "name": c.name,
                "group_id": c.group_id,
                "group_name": group_map.get(c.group_id, ""),
            }
            for c in result.scalars().all()
        ]

    has_data = bool(transactions)

    # ── Determine "current month" ─────────────────────────────────────────
    # Use the most recent month present in the data, capped to today's month.
    months_window = _last_n_months(12)
    current_month = months_window[-1]
    if transactions:
        most_recent_data_month = max(t["date"][:7] for t in transactions)
        if most_recent_data_month < current_month:
            current_month = most_recent_data_month

    # ── Monthly totals (raw — no outlier exclusion for trend chart) ───────
    monthly_totals = analysis_service.compute_monthly_totals(transactions, set())
    totals_by_month = {mt.month: mt for mt in monthly_totals}

    income_series = [
        _milliunit_to_float(totals_by_month[m].income) if m in totals_by_month else 0.0
        for m in months_window
    ]
    spending_series = [
        _milliunit_to_float(totals_by_month[m].spending) if m in totals_by_month else 0.0
        for m in months_window
    ]

    # ── Current month summary ─────────────────────────────────────────────
    current_totals = totals_by_month.get(current_month)
    income_this_month: int = current_totals.income if current_totals else 0
    spending_this_month: int = current_totals.spending if current_totals else 0
    net_this_month: int = current_totals.net if current_totals else 0

    # ── Category spend this month + IQR-adjusted averages ─────────────────
    cat_spend = analysis_service.compute_category_spend(
        transactions, categories, current_month, set()
    )
    cat_averages = analysis_service.compute_category_averages(transactions, categories)
    avg_by_id = {a["category_id"]: a for a in cat_averages}

    for cs in cat_spend:
        avg = avg_by_id.get(cs["category_id"])
        cs["average_amount"] = avg["average_amount"] if avg else 0
        cs["outlier_months_excluded"] = avg["outlier_months_excluded"] if avg else 0

    total_outlier_months_excluded = sum(
        a.get("outlier_months_excluded", 0) for a in cat_averages
    )

    # ── Trend chart JSON ──────────────────────────────────────────────────
    trend_chart_json: str | None = None
    if has_data:
        trend_chart_json = _safe_json({
            "data": [
                {
                    "type": "bar",
                    "name": "Income",
                    "x": months_window,
                    "y": income_series,
                    "marker": {"color": "#4caf82"},
                    "hovertemplate": "%{x}<br>Income: $%{y:,.2f}<extra></extra>",
                },
                {
                    "type": "bar",
                    "name": "Spending",
                    "x": months_window,
                    "y": spending_series,
                    "marker": {"color": "#ff6b6b"},
                    "hovertemplate": "%{x}<br>Spending: $%{y:,.2f}<extra></extra>",
                },
            ],
            "layout": {
                **_PLOTLY_BASE_LAYOUT,
                "barmode": "group",
                "height": 320,
                "margin": {"t": 20, "b": 50, "l": 70, "r": 20},
                "xaxis": {**_AXIS_STYLE},
                "yaxis": {**_AXIS_STYLE, "tickprefix": "$", "tickformat": ",.0f"},
            },
        })

    # ── Category chart JSON (top 15 categories, horizontal bar) ───────────
    category_chart_json: str | None = None
    if cat_spend:
        top_cats = cat_spend[:15]
        # Plotly horizontal bar: first item appears at bottom — reverse for top-to-bottom
        display_cats = list(reversed(top_cats))
        chart_height = max(280, len(display_cats) * 34 + 60)
        category_chart_json = _safe_json({
            "data": [
                {
                    "type": "bar",
                    "orientation": "h",
                    "name": "This month",
                    "x": [_milliunit_to_float(c["amount"]) for c in display_cats],
                    "y": [c["category_name"] for c in display_cats],
                    "marker": {"color": "#6c8fff"},
                    "hovertemplate": "%{y}<br>$%{x:,.2f}<extra></extra>",
                },
                {
                    "type": "bar",
                    "orientation": "h",
                    "name": "Avg (IQR-adjusted)",
                    "x": [_milliunit_to_float(c["average_amount"]) for c in display_cats],
                    "y": [c["category_name"] for c in display_cats],
                    "marker": {"color": "#2e3147", "line": {"color": "#6c8fff", "width": 1}},
                    "hovertemplate": "%{y}<br>Avg: $%{x:,.2f}<extra></extra>",
                },
            ],
            "layout": {
                **_PLOTLY_BASE_LAYOUT,
                "barmode": "overlay",
                "height": chart_height,
                "margin": {"t": 20, "b": 40, "l": 10, "r": 20},
                "xaxis": {**_AXIS_STYLE, "tickprefix": "$", "tickformat": ",.0f"},
                "yaxis": {**_AXIS_STYLE, "automargin": True},
            },
        })

    return templates.TemplateResponse("dashboard/dashboard.html", {
        "request": request,
        "budget_name": budget_name,
        "has_data": has_data,
        "last_sync": last_sync,
        "current_month": current_month,
        "net_worth": net_worth,
        "income_this_month": income_this_month,
        "spending_this_month": spending_this_month,
        "net_this_month": net_this_month,
        "cat_spend": cat_spend,
        "total_outlier_months_excluded": total_outlier_months_excluded,
        "trend_chart_json": trend_chart_json,
        "category_chart_json": category_chart_json,
    })
