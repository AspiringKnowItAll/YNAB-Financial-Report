from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Dashboard(Base):
    """
    A named dashboard that holds a collection of configurable widgets.

    Multiple dashboards are supported; one is marked is_default=True.
    The ``/`` route redirects to the default dashboard.

    custom_css is per-dashboard CSS injected into the page via ``| safe``.
    SECURITY NOTE: custom_css is intentionally unencrypted — display config,
    not a secret.  This app is single-user self-hosted; CSS injection is not
    in scope.
    """

    __tablename__ = "dashboard"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    grid_columns: Mapped[int] = mapped_column(Integer, default=12)
    default_time_period: Mapped[str | None] = mapped_column(String(32), nullable=True)
    custom_css: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String(32))
    updated_at: Mapped[str] = mapped_column(String(32))


class DashboardWidget(Base):
    """
    A single widget placed on a dashboard.

    Position and size are stored as grid coordinates for gridstack.js.
    config_json holds all per-widget options (time period, filters, etc.)
    as a JSON string.
    """

    __tablename__ = "dashboard_widget"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dashboard_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("dashboard.id"), nullable=False
    )
    widget_type: Mapped[str] = mapped_column(String(64), nullable=False)
    grid_x: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    grid_y: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    grid_w: Mapped[int] = mapped_column(Integer, default=4, nullable=False)
    grid_h: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    config_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    created_at: Mapped[str] = mapped_column(String(32))
    updated_at: Mapped[str] = mapped_column(String(32))


class NetWorthSnapshot(Base):
    """
    Point-in-time YNAB on-budget net worth recorded at each sync.

    Used by the net_worth_trend widget to chart balance over time.
    """

    __tablename__ = "net_worth_snapshot"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    budget_id: Mapped[str] = mapped_column(String(64), nullable=False)
    snapped_at: Mapped[str] = mapped_column(String(10), nullable=False)  # "YYYY-MM-DD"
    ynab_balance_milliunits: Mapped[int] = mapped_column(Integer, nullable=False)
