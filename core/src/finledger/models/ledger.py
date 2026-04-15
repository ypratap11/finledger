from datetime import datetime
from uuid import UUID
from sqlalchemy import BigInteger, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from finledger.models.inbox import Base


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = ({"schema": "ledger"},)
    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    code: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)
    normal_side: Mapped[str] = mapped_column(String, nullable=False)


class JournalEntry(Base):
    __tablename__ = "journal_entries"
    __table_args__ = (
        UniqueConstraint("source_event_id", name="uq_journal_source_event"),
        {"schema": "ledger"},
    )
    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    source_event_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("inbox.source_events.id"), nullable=True
    )
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="posted")
    preparer_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    approver_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    reverses: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("ledger.journal_entries.id"), nullable=True
    )
    memo: Mapped[str | None] = mapped_column(String, nullable=True)
    lines: Mapped[list["JournalLine"]] = relationship(
        "JournalLine", back_populates="entry", cascade="all, delete-orphan", lazy="selectin"
    )


class JournalLine(Base):
    __tablename__ = "journal_lines"
    __table_args__ = ({"schema": "ledger"},)
    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    entry_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("ledger.journal_entries.id", ondelete="CASCADE"), nullable=False
    )
    account_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("ledger.accounts.id"), nullable=False
    )
    side: Mapped[str] = mapped_column(String, nullable=False)
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String, nullable=False, default="USD")
    external_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    dimension_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    entry: Mapped["JournalEntry"] = relationship("JournalEntry", back_populates="lines")
