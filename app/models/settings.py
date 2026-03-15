from sqlalchemy import Boolean, Integer, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AppSettings(Base):
    """
    Singleton table (always id=1) holding all user-configured settings.
    Secrets (API keys, passwords) are stored Fernet-encrypted in *_enc columns (LargeBinary).
    Non-secret values (provider name, hosts, ports) are stored as plaintext.
    """

    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)

    # YNAB
    ynab_api_key_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    ynab_budget_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # AI provider
    ai_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ai_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ai_api_key_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    ai_base_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # Email / SMTP
    email_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    smtp_host: Mapped[str | None] = mapped_column(String(253), nullable=True)
    smtp_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    smtp_username: Mapped[str | None] = mapped_column(String(512), nullable=True)
    smtp_password_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    smtp_use_tls: Mapped[bool] = mapped_column(Boolean, default=True)
    smtp_from_email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    report_to_email: Mapped[str | None] = mapped_column(String(254), nullable=True)

    # Notion
    notion_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    notion_token_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    notion_database_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Scheduler
    schedule_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    schedule_frequency: Mapped[str | None] = mapped_column(String(16), nullable=True)   # "daily"|"weekly"|"biweekly"|"monthly"|"yearly"
    schedule_day_of_month: Mapped[int | None] = mapped_column(Integer, nullable=True)   # 1–28
    schedule_day_of_week: Mapped[str | None] = mapped_column(String(3), nullable=True)  # "mon"–"sun"
    schedule_month: Mapped[int | None] = mapped_column(Integer, nullable=True)          # 1–12 (yearly only)
    schedule_report_target: Mapped[str] = mapped_column(String(16), default="previous_month")  # "previous_month"|"current_month"
    schedule_send_email: Mapped[bool] = mapped_column(Boolean, default=False)

    # Wizard completion flag
    settings_complete: Mapped[bool] = mapped_column(Boolean, default=False)
