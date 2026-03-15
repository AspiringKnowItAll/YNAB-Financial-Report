from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Transaction(Base):
    """
    A single YNAB transaction (the core fact table).
    Monetary amounts are stored as milliunits (int, dollars × 1000).
    Soft-deleted rows are kept with deleted=True to mirror YNAB's deletion model.
    """

    __tablename__ = "transactions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # YNAB UUID
    budget_id: Mapped[str] = mapped_column(ForeignKey("budgets.id"))
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"))
    category_id: Mapped[str | None] = mapped_column(
        ForeignKey("categories.id"), nullable=True
    )

    date: Mapped[str] = mapped_column(String(10))          # ISO 8601: YYYY-MM-DD
    amount: Mapped[int] = mapped_column(Integer)            # milliunits
    memo: Mapped[str | None] = mapped_column(String(500), nullable=True)
    payee_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    cleared: Mapped[str] = mapped_column(String(16))        # "cleared", "uncleared", "reconciled"
    approved: Mapped[bool] = mapped_column(Boolean, default=True)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    import_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
