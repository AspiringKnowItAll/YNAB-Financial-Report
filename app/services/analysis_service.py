"""
Pure statistical analysis functions — no I/O, no database access.

All inputs and outputs are plain Python objects (lists, dicts).
These functions are called by report_service.py after data is loaded from DB.

Outlier detection uses Tukey's IQR fence:
  - Minimum 5 data points required; fewer → no outliers removed.
  - Q1 = 25th percentile, Q3 = 75th percentile, IQR = Q3 - Q1
  - Upper fence = Q3 + 1.5 × IQR, lower fence = Q1 - 1.5 × IQR
  - Spending categories: only upper outliers excluded.
  - Income: only lower outliers excluded.

Implemented in Phase 5.
"""

from app.schemas.report import MonthlyTotals, OutlierRecord


def detect_spending_outliers(amounts: list[int]) -> list[int]:
    """
    Return indices of upper-fence outliers in a list of spending milliunits.
    Requires at least 5 data points; returns [] otherwise.
    """
    raise NotImplementedError


def detect_income_outliers(amounts: list[int]) -> list[int]:
    """
    Return indices of lower-fence outliers in a list of income milliunits.
    Requires at least 5 data points; returns [] otherwise.
    """
    raise NotImplementedError


def compute_monthly_totals(
    transactions: list[dict],
    outlier_ids: set[str],
) -> list[MonthlyTotals]:
    """
    Aggregate transactions by month into MonthlyTotals.
    Transactions whose IDs are in outlier_ids are excluded from averages.
    """
    raise NotImplementedError


def compute_category_spend(
    transactions: list[dict],
    categories: list[dict],
    month: str,
    outlier_ids: set[str],
) -> list[dict]:
    """
    Compute per-category spending totals for a given month.
    Returns list of dicts suitable for constructing CategorySpend schemas.
    """
    raise NotImplementedError
