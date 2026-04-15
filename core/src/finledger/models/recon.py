from datetime import date, datetime
from uuid import UUID
from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column
from finledger.models.inbox import Base


class ReconRun(Base):
    __tablename__ = "recon_runs"
    __table_args__ = ({"schema": "recon"},)
    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    recon_type: Mapped[str] = mapped_column(String, nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    matched_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unmatched_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    mismatched_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class ReconBreak(Base):
    __tablename__ = "recon_breaks"
    __table_args__ = ({"schema": "recon"},)
    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("recon.recon_runs.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String, nullable=False)
    external_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    external_amount_cents: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    ledger_amount_cents: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
