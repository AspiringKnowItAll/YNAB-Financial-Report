"""
Widget data service — Phase 14, Milestones 3 & 4.

Dispatches widget data queries based on widget_type and applies the widget's
config_json filters (time period, account scope, category exclusions).

All chart data is returned as Plotly figure dicts (not HTML-escaped strings)
so the JS layer can call Plotly.newPlot() directly.

This service reads only from the database — no external HTTP calls.
"""

import json
import logging
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.budget import Category, CategoryGroup
from app.models.dashboard import DashboardWidget, NetWorthSnapshot
from app.models.import_data import ExternalAccount, ExternalBalance
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

# Colour palette for multi-series charts (group_rollup donut, etc.)
_COLOR_PALETTE: list[str] = [
    "#6c8fff", "#4caf82", "#ff6b6b", "#ffb347", "#a78bfa",
    "#f472b6", "#38bdf8", "#fbbf24", "#34d399", "#f87171",
    "#818cf8", "#fb923c",
]


# ---------------------------------------------------------------------------
# Time period helpers
# ---------------------------------------------------------------------------

def _24_month_floor(ref: date) -> date:
    """Return the first day of the month 24 months before *ref*."""
    month = ref.month - 24
    year = ref.year
    while month <= 0:
        month += 12
        year -= 1
    return date(year, month, 1)


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
        # Enforce the same 24-month cap on custom ranges
        floor = _24_month_floor(today)
        if s < floor:
            s = floor
        # The floor may have pushed s past e for ranges entirely in the past
        # (e.g. 2021-01 to 2021-12 with a floor of 2024-03). Widen end to
        # today so the clamped range is still valid rather than silently empty.
        if s > e:
            logger.warning(
                "Custom date range %s–%s was entirely before the 24-month "
                "floor (%s); widening end to today",
                custom_start,
                custom_end,
                floor.isoformat(),
            )
            e = today
        return s.isoformat(), e.isoformat()

    if time_period == "all_time":
        # Cap at 24 months — the chart window never exceeds this, and loading
        # unbounded transaction history would degrade over time.
        floor = _24_month_floor(today)
        return floor.isoformat(), today.isoformat()

    # ytd ends at the last day of the previous complete month.
    # Exception: in January no complete month exists yet, so it falls back to
    # today (current partial month) to avoid an inverted date range.
    if time_period == "ytd":
        start_ytd = date(today.year, 1, 1)
        first_of_this = today.replace(day=1)
        end_ytd = first_of_this - timedelta(days=1)
        # If no complete month exists yet (January), include the current partial month
        if end_ytd < start_ytd:
            end_ytd = today
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
    """Return a human-readable period label, e.g. 'Mar 2025 -- Feb 2026'."""
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
    result: list[str] = []
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
        if not isinstance(parsed, dict):
            logger.warning(
                "Widget %d: config_json is valid JSON but not an object (%s); using {}",
                widget.id,
                type(parsed).__name__,
            )
            return {}
        return parsed
    except (json.JSONDecodeError, TypeError):
        logger.warning("Widget %d: config_json could not be parsed; using {}", widget.id)
        return {}


def _widget_title(widget_type: str, config: dict) -> str:
    """Return the display title for a widget, honouring title_override."""
    override = config.get("title_override", "")
    if override and isinstance(override, str) and override.strip():
        return override.strip()
    return widget_type.replace("_", " ").title()


def _parse_account_ids(config: dict) -> list[str] | None:
    """Extract and validate included_account_ids from config."""
    raw = config.get("included_account_ids")
    if isinstance(raw, list) and raw:
        ids = [str(x) for x in raw if isinstance(x, str) and x]
        return ids if ids else None
    return None


def _parse_excluded_category_ids(config: dict) -> list[str] | None:
    """Extract and validate excluded_category_ids from config."""
    raw = config.get("excluded_category_ids")
    if isinstance(raw, list) and raw:
        ids = [str(x) for x in raw if isinstance(x, str) and x]
        return ids if ids else None
    return None


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
            "payee_name": t.payee_name,
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


async def _load_accounts(
    db: AsyncSession,
    budget_id: str,
    account_ids: list[str] | None = None,
) -> list[Account]:
    """Load non-deleted, non-closed YNAB accounts, optionally filtered by IDs."""
    query = select(Account).where(
        Account.budget_id == budget_id,
        Account.deleted.is_(False),
        Account.closed.is_(False),
    )
    if account_ids:
        query = query.where(Account.id.in_(account_ids))
    result = await db.execute(query)
    return list(result.scalars().all())


async def _load_account_name_map(db: AsyncSession, budget_id: str) -> dict[str, str]:
    """Return {account_id: account_name} for all non-deleted accounts."""
    result = await db.execute(
        select(Account.id, Account.name).where(
            Account.budget_id == budget_id,
            Account.deleted.is_(False),
        )
    )
    return {row.id: row.name for row in result.all()}


async def _load_net_worth_snapshots(
    db: AsyncSession,
    budget_id: str,
    start_date: str,
    end_date: str,
) -> list[NetWorthSnapshot]:
    """Load NetWorthSnapshot rows for the budget within the date range, ordered ascending."""
    result = await db.execute(
        select(NetWorthSnapshot)
        .where(
            NetWorthSnapshot.budget_id == budget_id,
            NetWorthSnapshot.snapped_at >= start_date,
            NetWorthSnapshot.snapped_at <= end_date,
        )
        .order_by(NetWorthSnapshot.snapped_at.asc())
    )
    return list(result.scalars().all())


async def _load_external_accounts_with_balances(
    db: AsyncSession,
) -> list[dict]:
    """
    Load all active external accounts with their most recent balance.

    Returns list of dicts: {id, name, institution, account_type, latest_balance, latest_date}
    """
    result = await db.execute(
        select(ExternalAccount).where(ExternalAccount.is_active.is_(True))
    )
    ext_accounts = list(result.scalars().all())

    accounts_with_balances: list[dict] = []
    for ea in ext_accounts:
        bal_result = await db.execute(
            select(ExternalBalance)
            .where(ExternalBalance.external_account_id == ea.id)
            .order_by(ExternalBalance.as_of_date.desc())
            .limit(1)
        )
        latest_bal = bal_result.scalar_one_or_none()
        accounts_with_balances.append({
            "id": ea.id,
            "name": ea.name,
            "institution": ea.institution,
            "account_type": ea.account_type,
            "latest_balance": latest_bal.balance_milliunits if latest_bal else 0,
            "latest_date": latest_bal.as_of_date if latest_bal else None,
        })

    return accounts_with_balances


async def _load_external_balances_in_range(
    db: AsyncSession,
    end_date: str,
) -> dict[int, list[dict]]:
    """
    Load external balance snapshots up to end_date, grouped by account.

    Returns: {external_account_id: [{as_of_date, balance_milliunits}, ...]}
    sorted ascending by date per account.

    Lower bound deliberately omitted: balances recorded before the widget
    period must still be available for the "latest on or before" snapshot
    lookup used by net_worth_trend.
    """
    active_result = await db.execute(
        select(ExternalAccount.id).where(ExternalAccount.is_active.is_(True))
    )
    active_ids = [row.id for row in active_result.all()]
    if not active_ids:
        return {}

    bal_result = await db.execute(
        select(ExternalBalance)
        .where(
            ExternalBalance.external_account_id.in_(active_ids),
            ExternalBalance.as_of_date <= end_date,
        )
        .order_by(ExternalBalance.as_of_date.asc())
    )
    grouped: dict[int, list[dict]] = defaultdict(list)
    for bal in bal_result.scalars().all():
        grouped[bal.external_account_id].append({
            "as_of_date": bal.as_of_date,
            "balance_milliunits": bal.balance_milliunits,
        })
    return grouped


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


def _savings_rate_card(
    transactions: list[dict], period_label: str, title: str
) -> dict:
    """Return savings rate as a percentage (float, NOT milliunits)."""
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
    savings_rate = ((income - spending) / income * 100) if income > 0 else 0.0
    return {
        "widget_type": "savings_rate_card",
        "title": title,
        "label": "Savings Rate",
        "value": round(savings_rate, 1),
        "period": period_label,
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

    # Never compare a partial current month against full-month averages.
    # Determine the last fully-complete calendar month (yesterday's month).
    today = date.today()
    last_complete_month = (today.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")

    # Determine the most recent *complete* month in the period that has spending data
    spending_months = {
        t["date"][:7]
        for t in transactions
        if t["amount"] < 0 and t["category_id"] is not None
    }
    target_month: str | None = None
    for m in reversed(months_in_period):
        if m <= last_complete_month and m in spending_months:
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

    # Build chart -- top 15 categories, displayed bottom-to-top
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


def _net_worth_trend(
    snapshots: list[NetWorthSnapshot],
    ext_balances_by_account: dict[int, list[dict]],
    period_label: str,
    title: str,
) -> dict:
    """Return Plotly line chart for net worth over time (YNAB + external)."""
    if not snapshots:
        return {
            "widget_type": "net_worth_trend",
            "title": title,
            "period": period_label,
            "empty": True,
            "plotly": None,
        }

    # Build a lookup: for each external account, all balances sorted by date
    # We'll use the latest balance on or before each YNAB snapshot date.
    dates: list[str] = []
    values: list[float] = []

    for snap in snapshots:
        snap_date = snap.snapped_at
        ynab_balance = snap.ynab_balance_milliunits

        # Sum external balances: for each account, latest balance on or before snap_date
        ext_total = 0
        for _acct_id, balances in ext_balances_by_account.items():
            latest_for_date: int | None = None
            for bal in balances:
                if bal["as_of_date"] <= snap_date:
                    latest_for_date = bal["balance_milliunits"]
                else:
                    break
            if latest_for_date is not None:
                ext_total += latest_for_date

        dates.append(snap_date)
        values.append(_milliunit_to_float(ynab_balance + ext_total))

    figure = {
        "data": [
            {
                "type": "scatter",
                "mode": "lines+markers",
                "name": "Net Worth",
                "x": dates,
                "y": values,
                "line": {"color": "#6c8fff", "width": 2},
                "marker": {"size": 5, "color": "#6c8fff"},
                "hovertemplate": "%{x}<br>Net Worth: $%{y:,.2f}<extra></extra>",
                "fill": "tozeroy",
                "fillcolor": "rgba(108, 143, 255, 0.1)",
            },
        ],
        "layout": {
            **_PLOTLY_BASE_LAYOUT,
            "height": 280,
            "margin": {"t": 10, "b": 50, "l": 80, "r": 10},
            "xaxis": {**_AXIS_STYLE},
            "yaxis": {**_AXIS_STYLE, "tickprefix": "$", "tickformat": ",.0f"},
        },
    }

    result: dict = {
        "widget_type": "net_worth_trend",
        "title": title,
        "period": period_label,
        "plotly": figure,
    }

    if len(snapshots) < 3:
        result["note"] = "YNAB history starts from first sync after Phase 14 deployment"

    return result


def _savings_rate_trend(
    transactions: list[dict],
    start_date: str,
    end_date: str,
    period_label: str,
    title: str,
) -> dict:
    """Return Plotly line chart for savings rate % per month."""
    months_window = _months_in_range(start_date, end_date)
    monthly_totals = analysis_service.compute_monthly_totals(transactions, set())
    totals_by_month = {mt.month: mt for mt in monthly_totals}

    rates: list[float] = []
    for m in months_window:
        if m in totals_by_month:
            mt = totals_by_month[m]
            if mt.income > 0:
                rates.append(round((mt.income - mt.spending) / mt.income * 100, 1))
            else:
                rates.append(0.0)
        else:
            rates.append(0.0)

    figure = {
        "data": [
            {
                "type": "scatter",
                "mode": "lines+markers",
                "name": "Savings Rate",
                "x": months_window,
                "y": rates,
                "line": {"color": "#4caf82", "width": 2},
                "marker": {"size": 5, "color": "#4caf82"},
                "hovertemplate": "%{x}<br>Savings Rate: %{y:.1f}%<extra></extra>",
                "fill": "tozeroy",
                "fillcolor": "rgba(76, 175, 130, 0.1)",
            },
        ],
        "layout": {
            **_PLOTLY_BASE_LAYOUT,
            "height": 280,
            "margin": {"t": 10, "b": 50, "l": 60, "r": 10},
            "xaxis": {**_AXIS_STYLE},
            "yaxis": {**_AXIS_STYLE, "ticksuffix": "%", "tickformat": ".0f"},
        },
    }

    return {
        "widget_type": "savings_rate_trend",
        "title": title,
        "period": period_label,
        "plotly": figure,
    }


def _group_rollup(
    transactions: list[dict],
    categories: list[dict],
    period_label: str,
    title: str,
    chart_type: str,
) -> dict:
    """Return Plotly chart for spending by category group."""
    cat_map = {c["id"]: c for c in categories}

    # Aggregate spending by group
    group_totals: dict[str, int] = defaultdict(int)
    for t in transactions:
        if t["amount"] >= 0 or t["category_id"] is None:
            continue
        cat = cat_map.get(t["category_id"])
        if cat is None:
            continue
        group_totals[cat["group_name"]] += abs(t["amount"])

    if not group_totals:
        return {
            "widget_type": "group_rollup",
            "title": title,
            "period": period_label,
            "empty": True,
            "plotly": None,
        }

    # Sort descending, take top 12
    sorted_groups = sorted(group_totals.items(), key=lambda x: x[1], reverse=True)[:12]

    if chart_type == "donut":
        labels = [g[0] for g in sorted_groups]
        amounts = [_milliunit_to_float(g[1]) for g in sorted_groups]
        colors = [_COLOR_PALETTE[i % len(_COLOR_PALETTE)] for i in range(len(sorted_groups))]

        figure = {
            "data": [
                {
                    "type": "pie",
                    "labels": labels,
                    "values": amounts,
                    "hole": 0.4,
                    "marker": {"colors": colors},
                    "textinfo": "label+percent",
                    "textposition": "outside",
                    "hovertemplate": "%{label}<br>$%{value:,.2f}<br>%{percent}<extra></extra>",
                },
            ],
            "layout": {
                **_PLOTLY_BASE_LAYOUT,
                "height": 320,
                "margin": {"t": 10, "b": 10, "l": 10, "r": 10},
                "showlegend": False,
            },
        }
    else:
        # Default: horizontal bar chart (sorted bottom-to-top for display)
        display_groups = list(reversed(sorted_groups))
        chart_height = max(250, len(display_groups) * 30 + 60)
        colors = [
            _COLOR_PALETTE[i % len(_COLOR_PALETTE)]
            for i in range(len(display_groups))
        ]

        figure = {
            "data": [
                {
                    "type": "bar",
                    "orientation": "h",
                    "name": "Spending",
                    "x": [_milliunit_to_float(g[1]) for g in display_groups],
                    "y": [g[0] for g in display_groups],
                    "marker": {"color": colors},
                    "hovertemplate": "%{y}<br>$%{x:,.2f}<extra></extra>",
                },
            ],
            "layout": {
                **_PLOTLY_BASE_LAYOUT,
                "height": chart_height,
                "margin": {"t": 10, "b": 40, "l": 10, "r": 10},
                "xaxis": {**_AXIS_STYLE, "tickprefix": "$", "tickformat": ",.0f"},
                "yaxis": {**_AXIS_STYLE, "automargin": True},
                "showlegend": False,
            },
        }

    return {
        "widget_type": "group_rollup",
        "title": title,
        "period": period_label,
        "plotly": figure,
    }


def _payee_breakdown(
    transactions: list[dict],
    period_label: str,
    title: str,
    top_n: int,
) -> dict:
    """Return Plotly horizontal bar chart for top spending payees."""
    # Aggregate spending by payee (outflows only, categorized only)
    payee_totals: dict[str, int] = defaultdict(int)
    for t in transactions:
        if t["amount"] >= 0 or t["category_id"] is None:
            continue
        payee = t.get("payee_name")
        if not payee or not isinstance(payee, str) or not payee.strip():
            continue
        payee_totals[payee.strip()] += abs(t["amount"])

    if not payee_totals:
        return {
            "widget_type": "payee_breakdown",
            "title": title,
            "period": period_label,
            "empty": True,
            "plotly": None,
        }

    # Sort descending, take top N
    sorted_payees = sorted(payee_totals.items(), key=lambda x: x[1], reverse=True)[:top_n]
    display_payees = list(reversed(sorted_payees))
    chart_height = max(250, len(display_payees) * 28 + 60)

    figure = {
        "data": [
            {
                "type": "bar",
                "orientation": "h",
                "name": "Spending",
                "x": [_milliunit_to_float(p[1]) for p in display_payees],
                "y": [p[0] for p in display_payees],
                "marker": {"color": "#ff6b6b"},
                "hovertemplate": "%{y}<br>$%{x:,.2f}<extra></extra>",
            },
        ],
        "layout": {
            **_PLOTLY_BASE_LAYOUT,
            "height": chart_height,
            "margin": {"t": 10, "b": 40, "l": 10, "r": 10},
            "xaxis": {**_AXIS_STYLE, "tickprefix": "$", "tickformat": ",.0f"},
            "yaxis": {**_AXIS_STYLE, "automargin": True},
            "showlegend": False,
        },
    }

    return {
        "widget_type": "payee_breakdown",
        "title": title,
        "period": period_label,
        "plotly": figure,
    }


def _month_over_month(
    transactions: list[dict],
    start_date: str,
    end_date: str,
    period_label: str,
    title: str,
) -> dict:
    """Return Plotly grouped bar chart with income/spending bars + net savings line."""
    months_window = _months_in_range(start_date, end_date)
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
    net_series = [
        _milliunit_to_float(totals_by_month[m].net) if m in totals_by_month else 0.0
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
            {
                "type": "scatter",
                "mode": "lines+markers",
                "name": "Net Savings",
                "x": months_window,
                "y": net_series,
                "line": {"color": "#ffb347", "width": 2, "dash": "dot"},
                "marker": {"size": 5, "color": "#ffb347"},
                "hovertemplate": "%{x}<br>Net: $%{y:,.2f}<extra></extra>",
            },
        ],
        "layout": {
            **_PLOTLY_BASE_LAYOUT,
            "barmode": "group",
            "height": 300,
            "margin": {"t": 10, "b": 50, "l": 70, "r": 10},
            "xaxis": {**_AXIS_STYLE},
            "yaxis": {**_AXIS_STYLE, "tickprefix": "$", "tickformat": ",.0f"},
        },
    }

    return {
        "widget_type": "month_over_month",
        "title": title,
        "period": period_label,
        "plotly": figure,
    }


def _category_stats_table(
    transactions: list[dict],
    categories: list[dict],
    period_label: str,
    title: str,
) -> dict:
    """
    Return per-category statistics table data.

    Computes avg (IQR-adjusted), min, max, peak month, and months with data
    for each category that has spending in the period.
    """
    cat_map = {c["id"]: c for c in categories}

    # Build per-category monthly totals: {cat_id: {month: total_milliunit}}
    cat_monthly: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for t in transactions:
        if t["category_id"] is None or t["amount"] >= 0:
            continue
        cat_monthly[t["category_id"]][t["date"][:7]] += abs(t["amount"])

    # Get IQR-adjusted averages from analysis_service
    cat_averages = analysis_service.compute_category_averages(transactions, categories)
    avg_by_id = {a["category_id"]: a for a in cat_averages}

    rows: list[dict] = []
    for cat_id, monthly in cat_monthly.items():
        cat = cat_map.get(cat_id)
        if cat is None:
            continue

        monthly_amounts = list(monthly.values())
        months_with_data = len(monthly_amounts)
        if months_with_data == 0:
            continue

        min_amount = min(monthly_amounts)
        max_amount = max(monthly_amounts)

        # Find the peak month
        peak_month = max(monthly.items(), key=lambda x: x[1])[0]

        # Get IQR-adjusted average
        avg_info = avg_by_id.get(cat_id)
        avg_amount = avg_info["average_amount"] if avg_info else (
            sum(monthly_amounts) // months_with_data
        )

        rows.append({
            "category_name": cat["name"],
            "group_name": cat.get("group_name", ""),
            "avg_amount": avg_amount,
            "min_amount": min_amount,
            "max_amount": max_amount,
            "peak_month": peak_month,
            "months_with_data": months_with_data,
        })

    # Sort by avg_amount descending
    rows.sort(key=lambda r: r["avg_amount"], reverse=True)

    return {
        "widget_type": "category_stats_table",
        "title": title,
        "period": period_label,
        "rows": rows,
    }


async def _account_balances_list(
    db: AsyncSession,
    budget_id: str,
    title: str,
    included_account_ids: list[str] | None,
) -> dict:
    """Return list of accounts with current balances (YNAB + external)."""
    # YNAB accounts
    ynab_accounts = await _load_accounts(db, budget_id, included_account_ids)
    ynab_sorted = sorted(ynab_accounts, key=lambda a: a.balance or 0, reverse=True)

    accounts: list[dict] = []
    total = 0

    for a in ynab_sorted:
        bal = a.balance or 0
        accounts.append({
            "name": a.name,
            "type": a.type,
            "balance": bal,
            "source": "ynab",
        })
        total += bal

    # External accounts
    ext_accounts = await _load_external_accounts_with_balances(db)
    ext_sorted = sorted(ext_accounts, key=lambda a: a["latest_balance"], reverse=True)

    for ea in ext_sorted:
        bal = ea["latest_balance"]
        accounts.append({
            "name": ea["name"],
            "type": ea["account_type"],
            "balance": bal,
            "source": "external",
        })
        total += bal

    return {
        "widget_type": "account_balances_list",
        "title": title,
        "accounts": accounts,
        "total": total,
    }


async def _recent_transactions(
    db: AsyncSession,
    budget_id: str,
    title: str,
    included_account_ids: list[str] | None,
    limit: int,
) -> dict:
    """Return recent transactions as structured data."""
    query = select(Transaction).where(
        Transaction.budget_id == budget_id,
        Transaction.deleted.is_(False),
        Transaction.approved.is_(True),
    )
    if included_account_ids:
        query = query.where(Transaction.account_id.in_(included_account_ids))
    query = query.order_by(Transaction.date.desc()).limit(limit)

    result = await db.execute(query)
    txns = list(result.scalars().all())

    # Load account names for display
    account_names = await _load_account_name_map(db, budget_id)

    transactions_list: list[dict] = []
    for t in txns:
        transactions_list.append({
            "date": t.date,
            "payee_name": t.payee_name or "",
            "amount": t.amount,
            "account_name": account_names.get(t.account_id, "Unknown"),
        })

    return {
        "widget_type": "recent_transactions",
        "title": title,
        "transactions": transactions_list,
    }


def _savings_projection(
    transactions: list[dict],
    start_date: str,
    end_date: str,
    period_label: str,
    title: str,
    annual_return_rate: float,
    projection_years: int,
    retirement_target_milliunits: int | None,
) -> dict:
    """
    Return Plotly projection chart for future savings balance using compound interest.

    Computes average monthly net savings from the transactions window, then
    projects forward `projection_years` years using the given annual return rate.
    An optional horizontal target line is shown when retirement_target_milliunits is set.
    """
    monthly_totals = analysis_service.compute_monthly_totals(transactions, set())

    if not monthly_totals:
        return {
            "widget_type": "savings_projection",
            "title": title,
            "period": period_label,
            "empty": True,
            "plotly": None,
        }

    avg_monthly_savings = sum(mt.net for mt in monthly_totals) / len(monthly_totals) / 1000.0

    monthly_rate = annual_return_rate / 12
    total_months = projection_years * 12

    today = date.today()
    future_dates: list[str] = []
    projected_balances: list[float] = []

    balance = 0.0
    for m in range(total_months + 1):
        month_offset = today.month + m - 1
        year = today.year + (month_offset // 12)
        month = (month_offset % 12) + 1
        future_dates.append(f"{year:04d}-{month:02d}-01")
        projected_balances.append(round(balance, 2))
        balance = balance * (1 + monthly_rate) + avg_monthly_savings

    shapes: list[dict] = []
    annotations: list[dict] = []

    if retirement_target_milliunits is not None:
        target_dollars = retirement_target_milliunits / 1000.0
        shapes.append({
            "type": "line",
            "x0": future_dates[0],
            "x1": future_dates[-1],
            "y0": target_dollars,
            "y1": target_dollars,
            "line": {"color": "#ffb347", "width": 1.5, "dash": "dash"},
            "yref": "y",
            "xref": "x",
        })
        annotations.append({
            "x": future_dates[-1],
            "y": target_dollars,
            "text": f"Target: ${target_dollars:,.0f}",
            "xanchor": "right",
            "yanchor": "bottom",
            "showarrow": False,
            "font": {"color": "#ffb347", "size": 11},
        })

    figure = {
        "data": [
            {
                "type": "scatter",
                "mode": "lines",
                "name": "Projected Savings",
                "x": future_dates,
                "y": projected_balances,
                "line": {"color": "#4caf82", "width": 2},
                "fill": "tozeroy",
                "fillcolor": "rgba(76, 175, 130, 0.1)",
                "hovertemplate": "%{x|%b %Y}<br>$%{y:,.0f}<extra></extra>",
            },
        ],
        "layout": {
            **_PLOTLY_BASE_LAYOUT,
            "height": 280,
            "margin": {"t": 10, "b": 50, "l": 80, "r": 10},
            "xaxis": {**_AXIS_STYLE},
            "yaxis": {**_AXIS_STYLE, "tickprefix": "$", "tickformat": ",.0f"},
            "shapes": shapes,
            "annotations": annotations,
        },
    }

    return {
        "widget_type": "savings_projection",
        "title": title,
        "period": period_label,
        "avg_monthly_savings": round(avg_monthly_savings, 2),
        "annual_return_rate_pct": round(annual_return_rate * 100, 1),
        "plotly": figure,
    }


async def _investment_tracker(
    db: AsyncSession,
    config: dict,
    title: str,
    annual_return_rate: float,
    projection_years: int,
) -> dict:
    """
    Return Plotly chart showing external investment account balance history + projected growth.

    Historical data is shown as solid lines; projections from the most recent
    balance are shown as dashed lines using compound interest.

    Config keys:
        included_external_account_ids: list of external account IDs (integers)
        projection_years: integer 1–30 (default 10)
    """
    raw_ext_ids = config.get("included_external_account_ids")
    ext_ids: list[int] | None = None
    if isinstance(raw_ext_ids, list) and raw_ext_ids:
        try:
            ext_ids = [int(x) for x in raw_ext_ids]
        except (ValueError, TypeError):
            ext_ids = None

    # Only include investment/retirement account types — applying compound interest
    # growth to liabilities (mortgages, credit cards) would be misleading.
    # Users can narrow further via included_external_account_ids in widget config.
    query = select(ExternalAccount).where(
        ExternalAccount.is_active.is_(True),
        ExternalAccount.account_type.in_(["investment", "retirement"]),
    )
    if ext_ids:
        query = query.where(ExternalAccount.id.in_(ext_ids))
    result = await db.execute(query)
    ext_accounts = list(result.scalars().all())

    if not ext_accounts:
        return {
            "widget_type": "investment_tracker",
            "title": title,
            "empty": True,
            "plotly": None,
        }

    today = date.today()
    total_months = projection_years * 12
    traces: list[dict] = []
    colors = [_COLOR_PALETTE[i % len(_COLOR_PALETTE)] for i in range(len(ext_accounts))]

    for idx, ea in enumerate(ext_accounts):
        color = colors[idx]

        bal_result = await db.execute(
            select(ExternalBalance)
            .where(ExternalBalance.external_account_id == ea.id)
            .order_by(ExternalBalance.as_of_date.asc())
        )
        balances = list(bal_result.scalars().all())

        if not balances:
            continue

        hist_dates = [b.as_of_date for b in balances]
        hist_values = [b.balance_milliunits / 1000.0 for b in balances]

        traces.append({
            "type": "scatter",
            "mode": "lines+markers",
            "name": ea.name + " (history)",
            "x": hist_dates,
            "y": hist_values,
            "line": {"color": color, "width": 2},
            "marker": {"size": 5, "color": color},
            "hovertemplate": "%{x}<br>" + ea.name + ": $%{y:,.0f}<extra></extra>",
        })

        latest_balance = hist_values[-1]
        monthly_rate = annual_return_rate / 12

        try:
            latest_date = date.fromisoformat(hist_dates[-1])
        except (ValueError, TypeError):
            latest_date = today

        proj_dates: list[str] = []
        proj_values: list[float] = []
        balance = latest_balance

        for m in range(total_months + 1):
            month_offset = latest_date.month + m - 1
            year = latest_date.year + (month_offset // 12)
            month = (month_offset % 12) + 1
            proj_dates.append(f"{year:04d}-{month:02d}-01")
            proj_values.append(round(balance, 2))
            balance = balance * (1 + monthly_rate)

        traces.append({
            "type": "scatter",
            "mode": "lines",
            "name": ea.name + " (projected)",
            "x": proj_dates,
            "y": proj_values,
            "line": {"color": color, "width": 1.5, "dash": "dash"},
            "hovertemplate": "%{x|%b %Y}<br>" + ea.name + " (proj): $%{y:,.0f}<extra></extra>",
        })

    if not traces:
        return {
            "widget_type": "investment_tracker",
            "title": title,
            "empty": True,
            "plotly": None,
        }

    figure = {
        "data": traces,
        "layout": {
            **_PLOTLY_BASE_LAYOUT,
            "height": 300,
            "margin": {"t": 10, "b": 50, "l": 80, "r": 10},
            "xaxis": {**_AXIS_STYLE},
            "yaxis": {**_AXIS_STYLE, "tickprefix": "$", "tickformat": ",.0f"},
        },
    }

    return {
        "widget_type": "investment_tracker",
        "title": title,
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

    Table/list widget response shape:
        {"widget_type", "title", ...type-specific fields...}

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
    """Inner implementation of get_widget_data -- all exceptions propagate to caller."""
    config = _parse_config(widget)
    title = _widget_title(widget.widget_type, config)

    # investment_tracker: external account history + projected growth (no YNAB txns needed)
    if widget.widget_type == "investment_tracker":
        annual_rate = (
            settings.projection_expected_return_rate
            if settings is not None and settings.projection_expected_return_rate is not None
            else 0.07
        )
        raw_years = config.get("projection_years", 10)
        try:
            projection_years = max(1, min(30, int(raw_years)))
        except (ValueError, TypeError):
            projection_years = 10
        return await _investment_tracker(db, config, title, annual_rate, projection_years)

    if settings is None or not settings.ynab_budget_id:
        return {
            "widget_type": widget.widget_type,
            "title": title,
            "error": "No budget configured",
        }
    budget_id: str = settings.ynab_budget_id

    # ── Widgets with special DB loading (no date-range transactions) ──────

    # net_worth_card does not use time-period transaction filtering
    if widget.widget_type == "net_worth_card":
        net_worth = await _load_net_worth(db, budget_id)
        return _net_worth_card(net_worth, title)

    # account_balances_list uses its own queries
    if widget.widget_type == "account_balances_list":
        included_account_ids = _parse_account_ids(config)
        return await _account_balances_list(db, budget_id, title, included_account_ids)

    # recent_transactions uses a separate date-desc limited query
    if widget.widget_type == "recent_transactions":
        included_account_ids = _parse_account_ids(config)
        raw_limit = config.get("limit", 20)
        if not isinstance(raw_limit, int):
            try:
                raw_limit = int(raw_limit)
            except (ValueError, TypeError):
                raw_limit = 20
        limit = max(5, min(100, raw_limit))
        return await _recent_transactions(db, budget_id, title, included_account_ids, limit)

    # ── Resolve date range from config ────────────────────────────────────

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

    # Account filter -- only non-empty strings are valid YNAB account UUIDs
    included_account_ids = _parse_account_ids(config)

    # Load transactions for the resolved date range
    transactions = await _load_transactions(
        db, budget_id, start_date, end_date, included_account_ids
    )

    # ── Card widgets -- no categories needed ──────────────────────────────

    if widget.widget_type == "income_card":
        return _income_card(transactions, period_label, title)
    if widget.widget_type == "spending_card":
        return _spending_card(transactions, period_label, title)
    if widget.widget_type == "net_savings_card":
        return _net_savings_card(transactions, period_label, title)
    if widget.widget_type == "savings_rate_card":
        return _savings_rate_card(transactions, period_label, title)

    if widget.widget_type == "savings_projection":
        annual_rate = (
            settings.projection_expected_return_rate
            if settings.projection_expected_return_rate is not None
            else 0.07
        )
        raw_years = config.get("projection_years", 10)
        try:
            projection_years = max(1, min(30, int(raw_years)))
        except (ValueError, TypeError):
            projection_years = 10
        return _savings_projection(
            transactions, start_date, end_date, period_label, title,
            annual_rate, projection_years, settings.projection_retirement_target,
        )

    # ── Chart/table widgets -- need categories ────────────────────────────

    excluded_category_ids = _parse_excluded_category_ids(config)
    categories = await _load_categories(db, budget_id, excluded_category_ids)

    if widget.widget_type == "income_spending_trend":
        return _income_spending_trend(
            transactions, start_date, end_date, period_label, title
        )
    if widget.widget_type == "category_breakdown":
        return _category_breakdown(
            transactions, categories, start_date, end_date, period_label, title
        )
    if widget.widget_type == "savings_rate_trend":
        return _savings_rate_trend(
            transactions, start_date, end_date, period_label, title
        )
    if widget.widget_type == "net_worth_trend":
        snapshots = await _load_net_worth_snapshots(db, budget_id, start_date, end_date)
        ext_balances = await _load_external_balances_in_range(db, end_date)
        return _net_worth_trend(snapshots, ext_balances, period_label, title)
    if widget.widget_type == "group_rollup":
        chart_type = config.get("chart_type", "bar")
        if chart_type not in ("bar", "donut"):
            chart_type = "bar"
        return _group_rollup(transactions, categories, period_label, title, chart_type)
    if widget.widget_type == "payee_breakdown":
        raw_top_n = config.get("top_n", 15)
        if not isinstance(raw_top_n, int):
            try:
                raw_top_n = int(raw_top_n)
            except (ValueError, TypeError):
                raw_top_n = 15
        top_n = max(1, min(30, raw_top_n))
        return _payee_breakdown(transactions, period_label, title, top_n)
    if widget.widget_type == "month_over_month":
        return _month_over_month(
            transactions, start_date, end_date, period_label, title
        )
    if widget.widget_type == "category_stats_table":
        return _category_stats_table(transactions, categories, period_label, title)

    # Unknown widget type -- not yet implemented
    logger.warning("Widget %d: unknown or unimplemented type: %s", widget.id, widget.widget_type)
    return {
        "widget_type": widget.widget_type,
        "title": title,
        "error": f"Widget type '{widget.widget_type}' is not yet implemented",
    }
