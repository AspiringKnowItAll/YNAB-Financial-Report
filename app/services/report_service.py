"""
Report assembly service.

Loads transaction and category data from the database, runs analysis,
calls the AI provider for commentary, and persists a ReportSnapshot.
"""

import json
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.budget import Category, CategoryGroup
from app.models.life_context import LifeContextBlock
from app.models.report import ReportSnapshot
from app.models.settings import AppSettings
from app.models.import_data import ExternalAccount, ExternalBalance, ExternalTransaction
from app.models.transaction import Transaction
from app.services import analysis_service
from app.services.ai_service import get_ai_provider
from app.services.encryption import decrypt


# ---------------------------------------------------------------------------
# Plotly helpers (same theme as dashboard)
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


def _milliunit_to_float(milliunits: int) -> float:
    return milliunits / 1000


def _milliunit_to_dollars(milliunits: int) -> str:
    return f"${milliunits / 1000:,.2f}"


def _last_n_months(anchor: str, n: int) -> list[str]:
    """Return n YYYY-MM strings ending at anchor (inclusive), ascending."""
    year, month = int(anchor[:4]), int(anchor[5:7])
    result = []
    for _ in range(n):
        result.append(f"{year:04d}-{month:02d}")
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    return list(reversed(result))


# ---------------------------------------------------------------------------
# AI prompt builder
# ---------------------------------------------------------------------------

def _build_ai_prompt(
    month: str,
    monthly_totals: list,
    cat_spend: list[dict],
    cat_averages_by_id: dict,
    outlier_months: list[dict],
    life_context: str | None,
    net_worth: int,
    external_data_text: str | None = None,
) -> tuple[str, str]:
    """
    Build (system_prompt, user_prompt) for the AI commentary.
    Returns plain-text prompts; the AI should respond in markdown prose.
    """
    system = (
        "You are a thoughtful, empathetic personal finance advisor. "
        "Given a household's monthly financial summary, write clear, "
        "actionable commentary in 3–4 paragraphs of plain prose. "
        "Do not use bullet points, headers, or lists. "
        "Be encouraging but honest. Avoid jargon. "
        "Respond in Markdown."
    )

    # Life context section
    if life_context:
        profile_lines = [life_context]
    else:
        profile_lines = ["(No personal context has been set up yet.)"]

    # Current month totals
    current = next((mt for mt in monthly_totals if mt.month == month), None)
    income_cur = current.income if current else 0
    spending_cur = current.spending if current else 0
    net_cur = current.net if current else 0

    # Previous month for comparison
    months_list = [mt.month for mt in monthly_totals]
    prev_month_label = ""
    prev_net = None
    if month in months_list:
        idx = months_list.index(month)
        if idx > 0:
            prev = monthly_totals[idx - 1]
            prev_month_label = prev.month
            prev_net = prev.net

    # Category spend lines (top 10)
    cat_lines = []
    for cs in cat_spend[:10]:
        avg_data = cat_averages_by_id.get(cs["category_id"])
        avg_amt = avg_data["average_amount"] if avg_data else 0
        this_amt = cs["amount"]
        if avg_amt > 0:
            pct = (this_amt - avg_amt) / avg_amt * 100
            vs = f"+{pct:.0f}% over avg" if pct > 5 else (f"{pct:.0f}% under avg" if pct < -5 else "on target")
        else:
            vs = "no history"
        cat_lines.append(
            f"  - {cs['category_name']} ({cs['group_name']}): "
            f"{_milliunit_to_dollars(this_amt)} "
            f"(avg: {_milliunit_to_dollars(avg_amt)}, {vs})"
        )

    # Outlier note
    outlier_lines = []
    for o in outlier_months:
        outlier_lines.append(
            f"  - {o['category_name']}: {o['month']} excluded "
            f"({_milliunit_to_dollars(o['amount_milliunit'])} — unusually high)"
        )

    user_parts = [
        f"Financial summary for **{month}**:",
        "",
        "**Personal Financial Context**",
        *profile_lines,
        "",
        "**Monthly Summary**",
        f"- Income: {_milliunit_to_dollars(income_cur)}",
        f"- Spending: {_milliunit_to_dollars(spending_cur)}",
        f"- Net: {_milliunit_to_dollars(net_cur)}",
        f"- Net worth: {_milliunit_to_dollars(net_worth)}",
    ]

    if prev_month_label and prev_net is not None:
        user_parts.append(f"- Previous month ({prev_month_label}) net: {_milliunit_to_dollars(prev_net)}")

    if external_data_text:
        user_parts += ["", "**External Accounts and Transactions**", external_data_text]

    if cat_lines:
        user_parts += ["", "**Top Spending Categories**", *cat_lines]

    if outlier_lines:
        user_parts += [
            "",
            "**Outlier Months Excluded from Averages**",
            *outlier_lines,
        ]

    user_parts += [
        "",
        "Please write a financial commentary for this month.",
    ]

    return system, "\n".join(user_parts)


# ---------------------------------------------------------------------------
# External data text builder
# ---------------------------------------------------------------------------

def _build_external_data_text(
    external_accounts: list,
    latest_balances: dict[int, "ExternalBalance"],
    external_transactions: list,
    month: str,
) -> str | None:
    """
    Format external account data as a plain-text block for the AI prompt.

    Returns None if there are no external accounts and no external transactions.
    """
    if not external_accounts and not external_transactions:
        return None

    acct_map: dict[int, ExternalAccount] = {a.id: a for a in external_accounts}
    sections: list[str] = []

    # Accounts section
    if external_accounts:
        lines = ["External Accounts (as of most recent balance dates):"]
        for acct in external_accounts:
            bal = latest_balances.get(acct.id)
            if bal is not None:
                lines.append(
                    f"- {acct.name}: {_milliunit_to_dollars(bal.balance_milliunits)} "
                    f"({acct.account_type}; as of {bal.as_of_date})"
                )
            else:
                lines.append(
                    f"- {acct.name}: (no balance recorded) ({acct.account_type})"
                )
        sections.append("\n".join(lines))

    # Transactions section
    if external_transactions:
        lines = [f"External Transactions ({month}):"]
        for txn in external_transactions:
            account_name = acct_map[txn.external_account_id].name if txn.external_account_id in acct_map else "Unknown"
            sign = "+" if txn.amount_milliunits >= 0 else "-"
            lines.append(
                f"- {txn.date} | {account_name} | "
                f"{sign}{_milliunit_to_dollars(abs(txn.amount_milliunits))} | "
                f"{txn.description}"
            )
        sections.append("\n".join(lines))

    return "\n\n".join(sections)


# ---------------------------------------------------------------------------
# Outlier month detection (for report snapshot storage)
# ---------------------------------------------------------------------------

def _detect_outlier_months(
    transactions: list[dict],
    categories: list[dict],
) -> list[dict]:
    """
    For each category, find months whose spending is above the Tukey upper
    fence. Returns list of {category_name, month, amount_milliunit}.
    """
    cat_map = {c["id"]: c for c in categories}
    cat_monthly: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for t in transactions:
        if t["category_id"] is None or t["amount"] >= 0:
            continue
        cat_monthly[t["category_id"]][t["date"][:7]] += abs(t["amount"])

    outliers = []
    for cat_id, monthly in cat_monthly.items():
        cat = cat_map.get(cat_id)
        if cat is None:
            continue
        months = sorted(monthly.keys())
        amounts = [monthly[m] for m in months]
        outlier_indices = analysis_service.detect_spending_outliers(amounts)
        for idx in outlier_indices:
            outliers.append({
                "category_name": cat["name"],
                "month": months[idx],
                "amount_milliunit": amounts[idx],
            })

    return outliers


# ---------------------------------------------------------------------------
# Chart JSON builders
# ---------------------------------------------------------------------------

def _build_trend_chart_json(monthly_totals: list, months_window: list[str]) -> str:
    totals_by_month = {mt.month: mt for mt in monthly_totals}
    income_series = [
        _milliunit_to_float(totals_by_month[m].income) if m in totals_by_month else 0.0
        for m in months_window
    ]
    spending_series = [
        _milliunit_to_float(totals_by_month[m].spending) if m in totals_by_month else 0.0
        for m in months_window
    ]
    data = {
        "data": [
            {
                "type": "bar", "name": "Income",
                "x": months_window, "y": income_series,
                "marker": {"color": "#4caf82"},
                "hovertemplate": "%{x}<br>Income: $%{y:,.2f}<extra></extra>",
            },
            {
                "type": "bar", "name": "Spending",
                "x": months_window, "y": spending_series,
                "marker": {"color": "#ff6b6b"},
                "hovertemplate": "%{x}<br>Spending: $%{y:,.2f}<extra></extra>",
            },
        ],
        "layout": {
            **_PLOTLY_BASE_LAYOUT,
            "barmode": "group", "height": 320,
            "margin": {"t": 20, "b": 50, "l": 70, "r": 20},
            "xaxis": {**_AXIS_STYLE},
            "yaxis": {**_AXIS_STYLE, "tickprefix": "$", "tickformat": ",.0f"},
        },
    }
    return (
        json.dumps(data)
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )


def _build_category_chart_json(cat_spend: list[dict]) -> str | None:
    if not cat_spend:
        return None
    top_cats = cat_spend[:15]
    display_cats = list(reversed(top_cats))
    chart_height = max(280, len(display_cats) * 34 + 60)
    data = {
        "data": [
            {
                "type": "bar", "orientation": "h",
                "name": "This month",
                "x": [_milliunit_to_float(c["amount"]) for c in display_cats],
                "y": [c["category_name"] for c in display_cats],
                "marker": {"color": "#6c8fff"},
                "hovertemplate": "%{y}<br>$%{x:,.2f}<extra></extra>",
            },
            {
                "type": "bar", "orientation": "h",
                "name": "Avg (IQR-adjusted)",
                "x": [_milliunit_to_float(c.get("average_amount", 0)) for c in display_cats],
                "y": [c["category_name"] for c in display_cats],
                "marker": {"color": "#2e3147", "line": {"color": "#6c8fff", "width": 1}},
                "hovertemplate": "%{y}<br>Avg: $%{x:,.2f}<extra></extra>",
            },
        ],
        "layout": {
            **_PLOTLY_BASE_LAYOUT,
            "barmode": "overlay", "height": chart_height,
            "margin": {"t": 20, "b": 40, "l": 10, "r": 20},
            "xaxis": {**_AXIS_STYLE, "tickprefix": "$", "tickformat": ",.0f"},
            "yaxis": {**_AXIS_STYLE, "automargin": True},
        },
    }
    return (
        json.dumps(data)
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------

async def generate_report(
    db: AsyncSession,
    settings: AppSettings,
    master_key: bytes,
    budget_id: str,
    month: str,
) -> ReportSnapshot:
    """
    Assemble report data, run outlier detection, generate AI commentary,
    build Plotly chart JSON, and persist a ReportSnapshot row.

    If a snapshot already exists for this (budget_id, month), it is
    overwritten with fresh data.

    Args:
        db: Async SQLAlchemy session.
        settings: AppSettings singleton (id=1).
        master_key: From app.state.master_key.
        budget_id: YNAB budget UUID.
        month: Target month in YYYY-MM format.

    Returns:
        The persisted ReportSnapshot ORM row.
    """
    # ── Load transactions ─────────────────────────────────────────────────
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

    # ── Load categories with group names ──────────────────────────────────
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

    # ── Net worth ─────────────────────────────────────────────────────────
    result = await db.execute(
        select(Account).where(
            Account.budget_id == budget_id,
            Account.deleted.is_(False),
            Account.closed.is_(False),
            Account.on_budget.is_(True),
        )
    )
    net_worth = sum(a.balance for a in result.scalars().all())

    # ── Analysis ──────────────────────────────────────────────────────────
    monthly_totals = analysis_service.compute_monthly_totals(transactions, set())
    months_window = _last_n_months(month, 12)

    cat_spend = analysis_service.compute_category_spend(
        transactions, categories, month, set()
    )
    cat_averages = analysis_service.compute_category_averages(transactions, categories)
    avg_by_id = {a["category_id"]: a for a in cat_averages}
    for cs in cat_spend:
        avg = avg_by_id.get(cs["category_id"])
        cs["average_amount"] = avg["average_amount"] if avg else 0
        cs["outlier_months_excluded"] = avg["outlier_months_excluded"] if avg else 0

    # ── Outlier months ────────────────────────────────────────────────────
    outlier_months = _detect_outlier_months(transactions, categories)

    # ── Life context block ────────────────────────────────────────────────
    life_context_text: str | None = None
    result = await db.execute(
        select(LifeContextBlock)
        .where(LifeContextBlock.archived.is_(False))
        .order_by(LifeContextBlock.version.desc())
        .limit(1)
    )
    context_block = result.scalar_one_or_none()
    if context_block is not None:
        try:
            life_context_text = decrypt(context_block.context_enc, master_key)
        except Exception:
            life_context_text = None

    # ── External accounts + transactions ─────────────────────────────────
    external_data_text: str | None = None
    try:
        ext_acct_result = await db.execute(
            select(ExternalAccount).where(ExternalAccount.is_active.is_(True))
        )
        ext_accounts = list(ext_acct_result.scalars().all())

        # Latest balance per account (most recent as_of_date)
        latest_balances: dict[int, ExternalBalance] = {}
        for acct in ext_accounts:
            bal_result = await db.execute(
                select(ExternalBalance)
                .where(ExternalBalance.external_account_id == acct.id)
                .order_by(ExternalBalance.as_of_date.desc())
                .limit(1)
            )
            bal = bal_result.scalar_one_or_none()
            if bal is not None:
                latest_balances[acct.id] = bal

        # External transactions for the report month
        month_start = f"{month}-01"
        _year, _mo = int(month[:4]), int(month[5:7])
        if _mo == 12:
            _next_year, _next_mo = _year + 1, 1
        else:
            _next_year, _next_mo = _year, _mo + 1
        month_end = f"{_next_year:04d}-{_next_mo:02d}-01"

        ext_txn_result = await db.execute(
            select(ExternalTransaction).where(
                ExternalTransaction.date >= month_start,
                ExternalTransaction.date < month_end,
            )
        )
        ext_transactions = list(ext_txn_result.scalars().all())

        external_data_text = _build_external_data_text(
            ext_accounts, latest_balances, ext_transactions, month
        )
    except Exception:
        import logging as _logging
        _logging.getLogger("app.services.report_service").exception(
            "Failed to load external data for report"
        )

    # ── AI commentary ─────────────────────────────────────────────────────
    ai_commentary: str | None = None
    if settings.ai_provider:
        try:
            ai_provider = get_ai_provider(settings, master_key)
            system_prompt, user_prompt = _build_ai_prompt(
                month=month,
                monthly_totals=monthly_totals,
                cat_spend=cat_spend,
                cat_averages_by_id=avg_by_id,
                outlier_months=outlier_months,
                life_context=life_context_text,
                net_worth=net_worth,
                external_data_text=external_data_text,
            )
            ai_commentary = await ai_provider.generate(
                system=system_prompt,
                user=user_prompt,
                max_tokens=1024,
            )
        except Exception as exc:
            # Store error note but don't fail the whole report
            ai_commentary = f"*AI commentary unavailable: {exc}*"

    # ── Chart JSON ────────────────────────────────────────────────────────
    chart_data = json.dumps({
        "trend": _build_trend_chart_json(monthly_totals, months_window),
        "category": _build_category_chart_json(cat_spend),
    })

    # ── Persist snapshot (upsert on budget_id + month) ───────────────────
    result = await db.execute(
        select(ReportSnapshot).where(
            ReportSnapshot.budget_id == budget_id,
            ReportSnapshot.month == month,
        )
    )
    snapshot = result.scalar_one_or_none()

    now_iso = datetime.now(timezone.utc).isoformat()

    if snapshot is None:
        snapshot = ReportSnapshot(
            budget_id=budget_id,
            month=month,
            generated_at=now_iso,
            ai_commentary=ai_commentary,
            outliers_excluded=json.dumps(outlier_months),
            chart_data=chart_data,
        )
        db.add(snapshot)
    else:
        snapshot.generated_at = now_iso
        snapshot.ai_commentary = ai_commentary
        snapshot.outliers_excluded = json.dumps(outlier_months)
        snapshot.chart_data = chart_data

    await db.commit()
    await db.refresh(snapshot)
    return snapshot


async def get_report(db: AsyncSession, report_id: int) -> ReportSnapshot | None:
    """Fetch a single report snapshot by ID."""
    result = await db.execute(
        select(ReportSnapshot).where(ReportSnapshot.id == report_id)
    )
    return result.scalar_one_or_none()


async def list_reports(
    db: AsyncSession, budget_id: str, limit: int = 24
) -> list[ReportSnapshot]:
    """List the most recent N report snapshots for a budget, newest first."""
    result = await db.execute(
        select(ReportSnapshot)
        .where(ReportSnapshot.budget_id == budget_id)
        .order_by(ReportSnapshot.month.desc())
        .limit(limit)
    )
    return list(result.scalars().all())
