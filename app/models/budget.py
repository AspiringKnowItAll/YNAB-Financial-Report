from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Budget(Base):
    """Top-level YNAB budget entity."""

    __tablename__ = "budgets"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # YNAB UUID
    name: Mapped[str] = mapped_column(String(256))
    currency_format: Mapped[str | None] = mapped_column(String(8), nullable=True)
    last_modified_on: Mapped[str | None] = mapped_column(String(32), nullable=True)

    category_groups: Mapped[list["CategoryGroup"]] = relationship(
        back_populates="budget", cascade="all, delete-orphan"
    )
    categories: Mapped[list["Category"]] = relationship(
        back_populates="budget", cascade="all, delete-orphan"
    )


class CategoryGroup(Base):
    """A top-level category group within a YNAB budget."""

    __tablename__ = "category_groups"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # YNAB UUID
    budget_id: Mapped[str] = mapped_column(ForeignKey("budgets.id"))
    name: Mapped[str] = mapped_column(String(256))
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)

    budget: Mapped["Budget"] = relationship(back_populates="category_groups")
    categories: Mapped[list["Category"]] = relationship(back_populates="group")


class Category(Base):
    """An individual spending category within a YNAB budget."""

    __tablename__ = "categories"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # YNAB UUID
    group_id: Mapped[str] = mapped_column(ForeignKey("category_groups.id"))
    budget_id: Mapped[str] = mapped_column(ForeignKey("budgets.id"))
    name: Mapped[str] = mapped_column(String(256))
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)

    # Goal fields (nullable — not all categories have goals)
    goal_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    goal_target: Mapped[int | None] = mapped_column(Integer, nullable=True)  # milliunits
    goal_percentage_complete: Mapped[int | None] = mapped_column(Integer, nullable=True)

    budget: Mapped["Budget"] = relationship(back_populates="categories")
    group: Mapped["CategoryGroup"] = relationship(back_populates="categories")
