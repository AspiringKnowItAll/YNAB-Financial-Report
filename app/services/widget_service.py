"""
Widget data service — Phase 14, Milestone 3.

Dispatches widget data queries based on widget_type and applies the widget's
config_json filters (time period, account scope, category exclusions).

All chart data is returned as Plotly figure dicts (not HTML-escaped strings)
so the JS layer can call Plotly.newPlot() directly.

This service reads only from the database — no external HTTP calls.
"""

import json
import logging
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.budget import Category, CategoryGroup
from app.models.dashboard import DashboardWidget
from app.models.settings import AppSettings
from app.models.transaction import Transaction
from app.services import analysis_service

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Plotly theme constants (kept in sync with report_service.py)
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
    "hoverlabel": {
        "bgcolor": "#1a1d27",
        "bordercolor": "#2e3147",
        "font": {"color": "#e2e4ef"},
    },
}

_AXIS_STYLE: dict = {
    "gridcolor": "#2e3147",
    "linecolor": "#2e3147",
    "zerolinecolor": "#2e3147",
}


# ---------------------------------------------------------------------------
# Time period helpers
# ---------------------------------------------------------------------------

def _resolve_date_range(
    time_period: str,
    custom_start: str | None = None,
    custom_end: str | None = None,
) -> tuple[str, str]:
    """
    Return (start_date, end_date) as YYYY-MM-DD strings for the given time period.

    For "last_N_months" periods, end_date is the last day of the most recent
    complete calendar month. start_date is the first day N months before that.
    """
    today = date.today()

    if time_period == "custom":
        if not custom_start or not custom_end:
            raise ValueError(
                "custom time period requires custom_start_date and custom_end_date"
            )
        try:
            s = date.fromisoformat(str(custom_start))
            e = date.fromisoformat(str(custom_end))
        except (ValueError, TypeError) as exc:
            raise ValueError(
                "custom_start_date and custom_end_date must be YYYY-MM-DD"
            ) from exc
        if s > e:
            raise ValueError("custom_start_date must not be after custom_end_date")
        return s.isoformat(), e.isoformat()

    if time_period == "all_time":
        return "2000-01-01", today.isoformat()

    # ytd ends at the last day of the previous complete month to be consistent
    # with last_N_months (which also excludes the partial current month).
    if time_period == "ytd":
        first_of_this = today.replace(day=1)
        end_ytd = first_of_this - timedelta(days=1)
        start_ytd = date(today.year, 1, 1)
        return start_ytd.isoformat(), end_ytd.isoformat()

    if time_period == "last_month":
        first_of_this = today.replace(day=1)
        end = first_of_this - timedelta(days=1)
        start = end.replace(day=1)
        return start.isoformat(), end.isoformat()

    n_map = {
        "last_3_months": 3,
        "last_6_months": 6,
        "last_12_months": 12,
        "last_18_months": 18,
        "last_24_months": 24,
    }
    if time_period not in n_map:
        logger.warning(
            "Unrecognized time_period %r; defaulting to last_12_months", time_period
        )
    n = n_map.get(time_period, 12)

    # End = last day of the most recent complete calendar month
    first_of_this = today.replace(day=1)
    end = first_of_this - timedelta(days=1)

    # Start = first day of n months before end (inclusive)
    start_month = end.month - (n - 1)
    start_year = end.year
    while start_month <= 0:
        start_month += 12
        start_year -= 1
    start = date(start_year, start_month, 1)

    return start.isoformat(), end.isoformat()


def _format_period_label(start_date: str, end_date: str) -> str:
    """Return a human-readable period label, e.g. 'Mar 2025 – Feb 2026'."""
    try:
        s = date.fromisoformat(start_date)
        e = date.fromisoformat(end_date)
        if s.year == e.year and s.month == e.month:
            return s.strftime("%b %Y")
        return f"{s.strftime('%b %Y')} \u2013 {e.strftime('%b %Y')}"
    except ValueError:
        return f"{start_date[:7]} \u2013 {end_date[:7]}"


def _months_in_range(start_date: str, end_date: str) -> list[str]:
    """Return all YYYY-MM strings from start_date to end_date, ascending."""
    try:
        s = date.fromisoformat(start_date)
        e = date.fromisoformat(end_date)
    except ValueError:
        return []
    result = []
    year, month = s.year, s.month
    while (year, month) <= (e.year, e.month):
        result.append(f"{year:04d}-{month:02d}")
        month += 1
        if month > 12:
            month = 1
            year += 1
    return result


def _milliunit_to_float(milliunits: int) -> float:
    return milliunits / 1000


# ---------------------------------------------------------------------------
# Config parsing
# ---------------------------------------------------------------------------

def _parse_config(widget: DashboardWidget) -> dict:
    """Parse widget.config_json safely, returning {} on any error or non-dict result."""
    try:
        parsed = json.loads(widget.config_json or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _widget_title(widget_type: str, config: dict) -> str:
    """Return the display title for a widget, honouring title_override."""
    override = config.get("title_override", "")
    if override and isinstance(override, str) and override.strip():
        return override.strip()
    return widget_type.replace("_", " ").title()


# ---------------------------------------------------------------------------
# Database loaders
# ---------------------------------------------------------------------------

async def _load_transactions(
    db: AsyncSession,
    budget_id: str,
    start_date: str,
    end_date: str,
    account_ids: list[str] | None = None,
) -> list[dict]:
    """
    Load approved, non-deleted transactions for a budget within a date range.

    If account_ids is provided and non-empty, only transactions for those
    accounts are returned.  Pass None or [] for no account filter.
    """
    query = select(Transaction).where(
        Transaction.budget_id == budget_id,
        Transaction.deleted.is_(False),
        Transaction.approved.is_(True),
        Transaction.date >= start_date,
        Transaction.date <= end_date,
    )
    if account_ids:
        query = query.where(Transaction.account_id.in_(account_ids))

    result = await db.execute(query)
    return [
        {
            "id": t.id,
            "date": t.date,
            "amount": t.amount,
            "category_id": t.category_id,
            "account_id": t.account_id,
        }
        for t in result.scalars().all()
    ]


async def _load_categories(
    db: AsyncSession,
    budget_id: str,
    excluded_ids: list[str] | None = None,
) -> list[dict]:
    """
    Load active, non-hidden categories with their group names for a budget.

    Categories whose IDs appear in excluded_ids are omitted.
    """
    query = (
        select(Category, CategoryGroup.name)
        .join(CategoryGroup, Category.group_id == CategoryGroup.id)
        .where(
            Category.budget_id == budget_id,
            Category.deleted.is_(False),
            Category.hidden.is_(False),
            CategoryGroup.deleted.is_(False),
            CategoryGroup.hidden.is_(False),
        )
    )
    if excluded_ids:
        query = query.where(Category.id.notin_(excluded_ids))

    result = await db.execute(query)
    return [
        {"id": cat.id, "name": cat.name, "group_name": group_name}
        for cat, group_name in result.all()
    ]


async def _load_net_worth(db: AsyncSession, budget_id: str) -> int:
    """Return sum of on-budget, non-deleted, non-closed YNAB account balances (milliunits)."""
    result = await db.execute(
        select(Account).where(
            Account.budget_id == budget_id,
            Account.deleted.is_(False),
            Account.closed.is_(False),
            Account.on_budget.is_(True),
        )
    )
    return sum(a.balance or 0 for a in result.scalars().all())


# ---------------------------------------------------------------------------
# Card widget builders
# ---------------------------------------------------------------------------

def _income_card(
    transactions: list[dict], period_label: str, title: str
) -> dict:
    total = sum(
        t["amount"]
        for t in transactions
        if t["amount"] > 0 and t["category_id"] is not None
    )
    return {
        "widget_type": "income_card",
        "title": title,
        "label": "Income",
        "value": total,
        "period": period_label,
    }


def _spending_card(
    transactions: list[dict], period_label: str, title: str
) -> dict:
    total = sum(
        abs(t["amount"])
        for t in transactions
        if t["amount"] < 0 and t["category_id"] is not None
    )
    return {
        "widget_type": "spending_card",
        "title": title,
        "label": "Spending",
        "value": total,
        "period": period_label,
    }


def _net_savings_card(
    transactions: list[dict], period_label: str, title: str
) -> dict:
    income = sum(
        t["amount"]
        for t in transactions
        if t["amount"] > 0 and t["category_id"] is not None
    )
    spending = sum(
        abs(t["amount"])
        for t in transactions
        if t["amount"] < 0 and t["category_id"] is not None
    )
    return {
        "widget_type": "net_savings_card",
        "title": title,
        "label": "Net Savings",
        "value": income - spending,
        "period": period_label,
    }


def _net_worth_card(net_worth: int, title: str) -> dict:
    return {
        "widget_type": "net_worth_card",
        "title": title,
        "label": "Net Worth",
        "value": net_worth,
        "period": "Current",
    }


# ---------------------------------------------------------------------------
# Chart widget builders
# ---------------------------------------------------------------------------

def _income_spending_trend(
    transactions: list[dict],
    start_date: str,
    end_date: str,
    period_label: str,
    title: str,
) -> dict:
    """Return Plotly figure dict for an income vs. spending grouped bar chart."""
    months_window = _months_in_range(start_date, end_date)
    monthly_totals = analysis_service.compute_monthly_totals(transactions, set())
    totals_by_month = {mt.month: mt for mt in monthly_totals}

    income_series = [
        _milliunit_to_float(totals_by_month[m].income) if m in totals_by_month else 0.0
        for m in months_window
    ]
    spending_series = [
        _milliunit_to_float(totals_by_month[m].spending)
        if m in totals_by_month
        else 0.0
        for m in months_window
    ]

    figure = {
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
            "height": 280,
            "margin": {"t": 10, "b": 50, "l": 70, "r": 10},
            "xaxis": {**_AXIS_STYLE},
            "yaxis": {**_AXIS_STYLE, "tickprefix": "$", "tickformat": ",.0f"},
        },
    }

    return {
        "widget_type": "income_spending_trend",
        "title": title,
        "period": period_label,
        "plotly": figure,
    }


def _category_breakdown(
    transactions: list[dict],
    categories: list[dict],
    start_date: str,
    end_date: str,
    period_label: str,
    title: str,
) -> dict:
    """
    Return Plotly figure dict for a horizontal category breakdown bar chart.

    Shows spending per category for the most recent complete month that has data
    within the configured period, with IQR-adjusted monthly averages computed
    over the full period window.
    """
    months_in_period = _months_in_range(start_date, end_date)

    # Determine the most recent month in the period that has any spending data
    spending_months = {
        t["date"][:7]
        for t in transactions
        if t["amount"] < 0 and t["category_id"] is not None
    }
    target_month: str | None = None
    for m in reversed(months_in_period):
        if m in spending_months:
            target_month = m
            break

    if not target_month:
        return {
            "widget_type": "category_breakdown",
            "title": title,
            "period": period_label,
            "empty": True,
            "plotly": None,
        }

    # Category spending for the target month
    cat_spend = analysis_service.compute_category_spend(
        transactions, categories, target_month, set()
    )
    if not cat_spend:
        return {
            "widget_type": "category_breakdown",
            "title": title,
            "period": period_label,
            "empty": True,
            "plotly": None,
        }

    # IQR-adjusted monthly averages over the full configured period
    cat_averages = analysis_service.compute_category_averages(transactions, categories)
    avg_by_id = {a["category_id"]: a for a in cat_averages}
    for cs in cat_spend:
        avg = avg_by_id.get(cs["category_id"])
        cs["average_amount"] = avg["average_amount"] if avg else 0

    # Build chart — top 15 categories, displayed bottom-to-top
    top_cats = cat_spend[:15]
    display_cats = list(reversed(top_cats))
    chart_height = max(250, len(display_cats) * 34 + 60)

    figure = {
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
                "x": [
                    _milliunit_to_float(c.get("average_amount", 0))
                    for c in display_cats
                ],
                "y": [c["category_name"] for c in display_cats],
                "marker": {
                    "color": "#2e3147",
                    "line": {"color": "#6c8fff", "width": 1},
                },
                "hovertemplate": "%{y}<br>Avg: $%{x:,.2f}<extra></extra>",
            },
        ],
        "layout": {
            **_PLOTLY_BASE_LAYOUT,
            "barmode": "overlay",
            "height": chart_height,
            "margin": {"t": 10, "b": 40, "l": 10, "r": 10},
            "xaxis": {**_AXIS_STYLE, "tickprefix": "$", "tickformat": ",.0f"},
            "yaxis": {**_AXIS_STYLE, "automargin": True},
        },
    }

    return {
        "widget_type": "category_breakdown",
        "title": title,
        "period": period_label,
        "target_month": target_month,
        "plotly": figure,
    }


# ---------------------------------------------------------------------------
# Main dispatcher
# ---------------------------------------------------------------------------

async def get_widget_data(
    widget: DashboardWidget,
    db: AsyncSession,
    settings: AppSettings | None,
) -> dict:
    """
    Return live data for a single widget.

    Parses config_json for time period, account scope, and category exclusions,
    then loads data from the database and returns widget-type-specific JSON.

    Card widget response shape:
        {"widget_type", "title", "label", "value" (milliunits int), "period"}

    Chart widget response shape:
        {"widget_type", "title", "period", "plotly": <Plotly figure dict>}

    Error response shape:
        {"widget_type", "error": <message string>}
    """
    try:
        return await _get_widget_data_inner(widget, db, settings)
    except Exception:
        logger.exception("Unhandled error in get_widget_data for widget %d", widget.id)
        return {
            "widget_type": widget.widget_type,
            "title": widget.widget_type.replace("_", " ").title(),
            "error": "Widget data unavailable",
        }


async def _get_widget_data_inner(
    widget: DashboardWidget,
    db: AsyncSession,
    settings: AppSettings | None,
) -> dict:
    """Inner implementation of get_widget_data — all exceptions propagate to caller."""
    config = _parse_config(widget)
    title = _widget_title(widget.widget_type, config)

    if settings is None or not settings.ynab_budget_id:
        return {
            "widget_type": widget.widget_type,
            "title": title,
            "error": "No budget configured",
        }
    budget_id: str = settings.ynab_budget_id

    # net_worth_card does not use time-period transaction filtering
    if widget.widget_type == "net_worth_card":
        net_worth = await _load_net_worth(db, budget_id)
        return _net_worth_card(net_worth, title)

    # Resolve date range from config
    time_period: str = config.get("time_period") or "last_12_months"
    try:
        start_date, end_date = _resolve_date_range(
            time_period,
            config.get("custom_start_date"),
            config.get("custom_end_date"),
        )
    except ValueError as exc:
        logger.warning("Widget %d: invalid time period config: %s", widget.id, exc)
        return {
            "widget_type": widget.widget_type,
            "title": title,
            "error": "Invalid time period configuration",
        }

    period_label = _format_period_label(start_date, end_date)

    # Account filter — only non-empty strings are valid YNAB account UUIDs
    raw_account_ids = config.get("included_account_ids")
    included_account_ids: list[str] | None = (
        [str(x) for x in raw_account_ids if isinstance(x, str) and x]
        if isinstance(raw_account_ids, list) and raw_account_ids
        else None
    )

    # Load transactions for the resolved date range
    transactions = await _load_transactions(
        db, budget_id, start_date, end_date, included_account_ids
    )

    # Card widgets — no categories needed
    if widget.widget_type == "income_card":
        return _income_card(transactions, period_label, title)
    if widget.widget_type == "spending_card":
        return _spending_card(transactions, period_label, title)
    if widget.widget_type == "net_savings_card":
        return _net_savings_card(transactions, period_label, title)

    # Chart widgets — need categories; only non-empty strings are valid category UUIDs
    raw_cat_ids = config.get("excluded_category_ids")
    excluded_category_ids: list[str] | None = (
        [str(x) for x in raw_cat_ids if isinstance(x, str) and x]
        if isinstance(raw_cat_ids, list) and raw_cat_ids
        else None
    )
    categories = await _load_categories(db, budget_id, excluded_category_ids)

    if widget.widget_type == "income_spending_trend":
        return _income_spending_trend(
            transactions, start_date, end_date, period_label, title
        )
    if widget.widget_type == "category_breakdown":
        return _category_breakdown(
            transactions, categories, start_date, end_date, period_label, title
        )

    # Unknown widget type — not yet implemented
    logger.warning("Widget %d: unknown or unimplemented type: %s", widget.id, widget.widget_type)
    return {
        "widget_type": widget.widget_type,
        "title": title,
        "error": f"Widget type '{widget.widget_type}' is not yet implemented",
    }
