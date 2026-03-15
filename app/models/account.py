from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Account(Base):
    """
    A YNAB budget account (checking, savings, credit card, etc.).
    Balances are stored as milliunits (int, dollars × 1000).
    Soft-deleted rows are kept with deleted=True to mirror YNAB's deletion model.
    """

    __tablename__ = "accounts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # YNAB UUID
    budget_id: Mapped[str] = mapped_column(ForeignKey("budgets.id"))
    name: Mapped[str] = mapped_column(String(256))
    type: Mapped[str] = mapped_column(String(32))           # e.g. "checking", "creditCard"
    on_budget: Mapped[bool] = mapped_column(Boolean, default=True)
    closed: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)

    balance: Mapped[int] = mapped_column(Integer, default=0)            # milliunits
    cleared_balance: Mapped[int] = mapped_column(Integer, default=0)    # milliunits
    uncleared_balance: Mapped[int] = mapped_column(Integer, default=0)  # milliunits
