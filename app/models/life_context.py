from sqlalchemy import Boolean, Integer, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class LifeContextSession(Base):
    """
    One chat session between the user and the AI life-context assistant.

    Messages are stored as a JSON array encrypted with the master key:
        [{"role": "user"|"assistant", "content": str}, ...]

    A session is "active" while ended_at IS NULL.
    compressed_at is set (alongside ended_at) when the user clicks
    "End Chat Session" and compression fires.
    """

    __tablename__ = "life_context_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[str] = mapped_column(String(32))                       # ISO datetime
    ended_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    compressed_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    messages_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)


class LifeContextBlock(Base):
    """
    A compressed "financial life story" context block produced by the AI
    at the end of a chat session.

    Blocks are versioned; previous versions are archived (archived=True)
    rather than deleted. There is at most one current block (archived=False).

    context_enc decrypts to a plain-text string of ≤5000 characters.
    """

    __tablename__ = "life_context_blocks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version: Mapped[int] = mapped_column(Integer)                             # Increments per compression
    created_at: Mapped[str] = mapped_column(String(32))                       # ISO datetime
    context_enc: Mapped[bytes] = mapped_column(LargeBinary)                   # Encrypted text ≤5000 chars
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    # archived=False → current block (at most one at a time)
    # archived=True  → historical version (kept forever, never deleted)
