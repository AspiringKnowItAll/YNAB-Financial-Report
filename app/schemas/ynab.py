"""
Pydantic models for deserialising YNAB API v1 responses.
Only the fields used by this application are included.
"""

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------

class YnabBudgetSummary(BaseModel):
    id: str
    name: str
    last_modified_on: str | None = None
    currency_format: dict | None = None


class YnabBudgetListResponse(BaseModel):
    budgets: list[YnabBudgetSummary]


# ---------------------------------------------------------------------------
# Category / CategoryGroup
# ---------------------------------------------------------------------------

class YnabCategory(BaseModel):
    id: str
    category_group_id: str
    name: str
    hidden: bool = False
    deleted: bool = False
    goal_type: str | None = None
    goal_target: int | None = None                # milliunits
    goal_percentage_complete: int | None = None


class YnabCategoryGroup(BaseModel):
    id: str
    name: str
    hidden: bool = False
    deleted: bool = False
    categories: list[YnabCategory] = []


# ---------------------------------------------------------------------------
# Account
# ---------------------------------------------------------------------------

class YnabAccount(BaseModel):
    id: str
    name: str
    type: str
    on_budget: bool = True
    closed: bool = False
    deleted: bool = False
    balance: int = 0            # milliunits
    cleared_balance: int = 0    # milliunits
    uncleared_balance: int = 0  # milliunits


# ---------------------------------------------------------------------------
# Transaction
# ---------------------------------------------------------------------------

class YnabTransaction(BaseModel):
    id: str
    account_id: str
    category_id: str | None = None
    date: str                   # YYYY-MM-DD
    amount: int                 # milliunits
    memo: str | None = None
    payee_name: str | None = None
    cleared: str = "uncleared"
    approved: bool = True
    deleted: bool = False
    import_id: str | None = None


class YnabTransactionListResponse(BaseModel):
    transactions: list[YnabTransaction]
    server_knowledge: int
