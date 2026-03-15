from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class UserProfile(Base):
    """
    Singleton table (always id=1) holding user-provided personal context
    gathered during the profile setup wizard. This context informs AI report
    generation (household size, income type, financial goals, etc.).
    """

    __tablename__ = "user_profile"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)

    household_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    income_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    financial_goals: Mapped[str | None] = mapped_column(Text, nullable=True)
    housing_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    setup_complete: Mapped[bool] = mapped_column(Boolean, default=False)
