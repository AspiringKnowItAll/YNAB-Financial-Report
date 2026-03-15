"""
Pydantic models for report assembly and rendering.
These are in-memory data structures — not stored directly in the DB.
"""

from pydantic import BaseModel


class CategorySpend(BaseModel):
    category_id: str
    category_name: str
    group_name: str
    amount: int                 # milliunits (negative = outflow in YNAB)
    is_outlier_excluded: bool = False


class MonthlyTotals(BaseModel):
    month: str                  # YYYY-MM
    income: int                 # milliunits
    spending: int               # milliunits (positive = total outflow)
    net: int                    # milliunits (income - spending)


class OutlierRecord(BaseModel):
    transaction_id: str
    date: str
    payee_name: str | None
    category_name: str | None
    amount: int                 # milliunits
    reason: str                 # e.g. "upper IQR fence exceeded"


class ReportData(BaseModel):
    """Assembled report data passed to the report service and AI service."""

    budget_id: str
    month: str                              # YYYY-MM
    monthly_totals: list[MonthlyTotals]     # last N months for trend charts
    category_spend: list[CategorySpend]     # current month breakdown
    outliers_excluded: list[OutlierRecord]
    user_context: dict                      # from UserProfile (household_size, etc.)
