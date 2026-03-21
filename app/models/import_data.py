from sqlalchemy import Boolean, ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class InstitutionProfile(Base):
    """
    Remembered format hints for a financial institution.

    Saved after a confirmed import when the user opts in. Used as additional
    context in the AI normalization prompt on future uploads from the same
    institution.

    format_hints is a JSON string containing detected column names/positions,
    date format, amount format, and account name patterns.
    """

    __tablename__ = "institution_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(256))
    format_hints: Mapped[str | None] = mapped_column(Text, nullable=True)   # JSON string
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)          # AI-generated summary
    created_at: Mapped[str] = mapped_column(String(32))                     # ISO datetime
    updated_at: Mapped[str] = mapped_column(String(32))                     # ISO datetime


class ImportSession(Base):
    """
    One file upload + review session.

    Tracks the lifecycle of a single imported document from upload through
    confirmation. messages_enc and extracted_data_enc are Fernet-encrypted
    (defense in depth on top of SQLCipher). file_content_enc is cleared
    (set to NULL) after the user confirms the import.

    status values:    pending | processing | reviewing | confirmed | cancelled | failed
    data_type values: transactions | balances | both | unknown
    """

    __tablename__ = "import_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_name: Mapped[str] = mapped_column(String(512))
    file_hash: Mapped[str] = mapped_column(String(64))                      # SHA-256 hex (plaintext — it's a hash)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    data_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    institution_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    messages_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)         # Fernet-encrypted JSON
    extracted_data_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)   # Fernet-encrypted JSON
    file_content_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)     # Cleared after confirm
    created_at: Mapped[str] = mapped_column(String(32))                     # ISO datetime
    confirmed_at: Mapped[str | None] = mapped_column(String(32), nullable=True)  # ISO datetime


class ExternalAccount(Base):
    """
    A financial account sourced from an imported document (not YNAB).

    ynab_account_id optionally links to a YNAB account (stored as the YNAB
    UUID string — YNAB accounts are synced separately and may not exist yet).
    is_active=False hides the account from reports without deleting history.

    account_type values: checking | savings | investment | retirement |
                         credit | loan | mortgage | other
    """

    __tablename__ = "external_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(256))
    institution: Mapped[str | None] = mapped_column(String(256), nullable=True)
    account_type: Mapped[str] = mapped_column(String(32))
    ynab_account_id: Mapped[str | None] = mapped_column(String(64), nullable=True)  # YNAB UUID, optional
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[str] = mapped_column(String(32))                     # ISO datetime


class ExternalTransaction(Base):
    """
    A single transaction row extracted from an imported document.

    amount_milliunits follows YNAB convention (dollars × 1000, signed:
    negative = outflow, positive = inflow).
    """

    __tablename__ = "external_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    external_account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("external_accounts.id"), nullable=False
    )
    date: Mapped[str] = mapped_column(String(16))                           # ISO date: YYYY-MM-DD
    amount_milliunits: Mapped[int] = mapped_column(Integer)                 # Signed; negative = outflow
    description: Mapped[str] = mapped_column(String(512))
    category: Mapped[str | None] = mapped_column(String(256), nullable=True)
    import_session_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("import_sessions.id"), nullable=True
    )
    created_at: Mapped[str] = mapped_column(String(32))                     # ISO datetime


class ExternalBalance(Base):
    """
    A point-in-time balance snapshot for an external account.

    balance_milliunits is the total account balance (dollars × 1000).
    return_bps is basis points (return % × 100); e.g. 7.5% = 750 bps.
    contribution_milliunits and return_bps are optional (investment/retirement accounts).
    """

    __tablename__ = "external_balances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    external_account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("external_accounts.id"), nullable=False
    )
    balance_milliunits: Mapped[int] = mapped_column(Integer)                # Total balance, dollars × 1000
    as_of_date: Mapped[str] = mapped_column(String(16))                     # ISO date: YYYY-MM-DD
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    contribution_milliunits: Mapped[int | None] = mapped_column(Integer, nullable=True)
    return_bps: Mapped[int | None] = mapped_column(Integer, nullable=True)  # Basis points; 7.5% = 750
    import_session_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("import_sessions.id"), nullable=True
    )
    created_at: Mapped[str] = mapped_column(String(32))                     # ISO datetime
