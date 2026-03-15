"""
Pure statistical analysis functions — no I/O, no database access.

All inputs and outputs are plain Python objects (lists, dicts).
These functions are called by dashboard.py and report_service.py after data
is loaded from the DB.

Outlier detection uses Tukey's IQR fence:
  - Minimum 5 data points required; fewer → no outliers removed.
  - Q1 = 25th percentile, Q3 = 75th percentile, IQR = Q3 - Q1
  - Upper fence = Q3 + 1.5 × IQR, lower fence = Q1 - 1.5 × IQR
  - Spending categories: only upper outliers excluded (unusually high months).
  - Income: only lower outliers excluded (unusually low months).

Outlier detection operates at the per-category monthly-total level — e.g. if a
category normally costs $100/month but one month had $1,000, that month is
excluded from the average. Raw monthly totals (for trend charts) are never
modified; outlier exclusion only affects average calculations.
"""

import statistics
from collections import defaultdict

from app.schemas.report import MonthlyTotals, OutlierRecord


# ---------------------------------------------------------------------------
# IQR fence helpers
# ---------------------------------------------------------------------------

def detect_spending_outliers(amounts: list[int]) -> list[int]:
    """
    Return indices of upper-fence outliers in a list of spending milliunits.

    Intended for per-category monthly spending totals: a month whose total is
    unusually high (e.g. a one-time large purchase) is flagged as an outlier
    so it can be excluded from the long-run average.

    Requires at least 5 data points; returns [] if fewer.
    """
    if len(amounts) < 5:
        return []
    q1, _, q3 = statistics.quantiles(amounts, n=4)
    upper_fence = q3 + 1.5 * (q3 - q1)
    return [i for i, a in enumerate(amounts) if a > upper_fence]


def detect_income_outliers(amounts: list[int]) -> list[int]:
    """
    Return indices of lower-fence outliers in a list of income milliunits.

    Intended for per-category monthly income totals: a month whose income is
    unusually low is flagged so it can be excluded from the long-run average.

    Requires at least 5 data points; returns [] if fewer.
    """
    if len(amounts) < 5:
        return []
    q1, _, q3 = statistics.quantiles(amounts, n=4)
    lower_fence = q1 - 1.5 * (q3 - q1)
    return [i for i, a in enumerate(amounts) if a < lower_fence]


# ---------------------------------------------------------------------------
# Monthly aggregation
# ---------------------------------------------------------------------------

def compute_monthly_totals(
    transactions: list[dict],
    outlier_ids: set[str],
) -> list[MonthlyTotals]:
    """
    Aggregate transactions by calendar month into MonthlyTotals.

    Transactions whose IDs are in outlier_ids are excluded (reserved for
    Phase 6 AI report assembly; pass an empty set for the dashboard).

    Only categorised transactions are counted (category_id is not None).
    Un-categorised transactions are internal account transfers and are skipped.

    Returns results sorted ascending by month (YYYY-MM).
    """
    monthly: dict[str, dict[str, int]] = defaultdict(lambda: {"income": 0, "spending": 0})

    for t in transactions:
        if t["id"] in outlier_ids:
            continue
        if t["category_id"] is None:
            continue  # skip internal transfers

        month = t["date"][:7]  # YYYY-MM
        amount = t["amount"]   # milliunits; positive = inflow, negative = outflow

        if amount > 0:
            monthly[month]["income"] += amount
        else:
            monthly[month]["spending"] += abs(amount)

    return [
        MonthlyTotals(
            month=m,
            income=v["income"],
            spending=v["spending"],
            net=v["income"] - v["spending"],
        )
        for m, v in sorted(monthly.items())
    ]


# ---------------------------------------------------------------------------
# Category breakdown
# ---------------------------------------------------------------------------

def compute_category_spend(
    transactions: list[dict],
    categories: list[dict],
    month: str,
    outlier_ids: set[str],
) -> list[dict]:
    """
    Compute per-category spending totals for a single month (YYYY-MM).

    Only outflow transactions (amount < 0) with a category are included.
    Transactions in outlier_ids are skipped.

    Returns a list of dicts (suitable for CategorySpend schema), sorted
    descending by amount (largest spend first).
    """
    cat_map = {c["id"]: c for c in categories}
    totals: dict[str, int] = defaultdict(int)

    for t in transactions:
        if t["date"][:7] != month:
            continue
        if t["id"] in outlier_ids:
            continue
        if t["category_id"] is None:
            continue
        if t["amount"] >= 0:
            continue  # skip inflows

        totals[t["category_id"]] += abs(t["amount"])

    result = []
    for cat_id, amount in totals.items():
        cat = cat_map.get(cat_id)
        if cat is None:
            continue
        result.append({
            "category_id": cat_id,
            "category_name": cat["name"],
            "group_name": cat.get("group_name", ""),
            "amount": amount,
            "is_outlier_excluded": False,
        })

    return sorted(result, key=lambda x: x["amount"], reverse=True)


def compute_category_averages(
    transactions: list[dict],
    categories: list[dict],
) -> list[dict]:
    """
    For each category, compute the average monthly spending across all months
    that have data, using Tukey's IQR fence to exclude outlier months.

    This prevents one unusually expensive month (e.g. an annual subscription,
    a car repair) from inflating the perceived "normal" monthly cost.

    Returns a list of dicts sorted descending by average_amount:
        {
            "category_id": str,
            "category_name": str,
            "group_name": str,
            "average_amount": int,          # milliunits, outlier months excluded
            "raw_average_amount": int,       # milliunits, no exclusion
            "outlier_months_excluded": int,  # number of months excluded
            "months_with_data": int,
        }
    """
    cat_map = {c["id"]: c for c in categories}

    # Build per-category monthly totals: {cat_id: {month: total_milliunit}}
    cat_monthly: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for t in transactions:
        if t["category_id"] is None:
            continue
        if t["amount"] >= 0:
            continue  # only outflows

        cat_monthly[t["category_id"]][t["date"][:7]] += abs(t["amount"])

    result = []
    for cat_id, monthly in cat_monthly.items():
        cat = cat_map.get(cat_id)
        if cat is None:
            continue

        monthly_amounts = list(monthly.values())
        months_with_data = len(monthly_amounts)

        raw_average = sum(monthly_amounts) // months_with_data if monthly_amounts else 0

        outlier_indices = set(detect_spending_outliers(monthly_amounts))
        clean_amounts = [a for i, a in enumerate(monthly_amounts) if i not in outlier_indices]
        outlier_months_excluded = len(outlier_indices)

        average = sum(clean_amounts) // len(clean_amounts) if clean_amounts else raw_average

        result.append({
            "category_id": cat_id,
            "category_name": cat["name"],
            "group_name": cat.get("group_name", ""),
            "average_amount": average,
            "raw_average_amount": raw_average,
            "outlier_months_excluded": outlier_months_excluded,
            "months_with_data": months_with_data,
        })

    return sorted(result, key=lambda x: x["average_amount"], reverse=True)
