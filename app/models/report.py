from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ReportSnapshot(Base):
    """
    A persisted monthly report. Stores the AI commentary (markdown),
    serialised chart data (JSON), and a list of outlier transactions
    that were excluded from trend averages (JSON array).
    """

    __tablename__ = "report_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    budget_id: Mapped[str] = mapped_column(ForeignKey("budgets.id"))
    month: Mapped[str] = mapped_column(String(7))           # YYYY-MM
    generated_at: Mapped[str] = mapped_column(String(32))   # ISO 8601 datetime string
    ai_commentary: Mapped[str | None] = mapped_column(Text, nullable=True)
    outliers_excluded: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON array
    chart_data: Mapped[str | None] = mapped_column(Text, nullable=True)         # JSON object


class SyncLog(Base):
    """
    One row per YNAB sync attempt. A row is inserted with status="running"
    at the start and updated to "success" or "failed" at the end.
    A row must never remain permanently in "running" state.
    """

    __tablename__ = "sync_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    budget_id: Mapped[str | None] = mapped_column(ForeignKey("budgets.id"), nullable=True)
    started_at: Mapped[str] = mapped_column(String(32))     # ISO 8601 datetime string
    finished_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(16))         # "running" | "success" | "failed"
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    transactions_added: Mapped[int] = mapped_column(Integer, default=0)
    transactions_updated: Mapped[int] = mapped_column(Integer, default=0)
    knowledge_of_server: Mapped[int | None] = mapped_column(Integer, nullable=True)
