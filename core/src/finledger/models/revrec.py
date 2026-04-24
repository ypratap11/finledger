from datetime import date, datetime
from uuid import UUID
from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from finledger.models.inbox import Base


class Contract(Base):
    __tablename__ = "contracts"
    __table_args__ = ({"schema": "revrec"},)
    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    external_ref: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    customer_id: Mapped[str | None] = mapped_column(String, nullable=True)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    total_amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String, nullable=False, default="USD")
    created_from_event_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("inbox.source_events.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    obligations: Mapped[list["PerformanceObligation"]] = relationship(
        "PerformanceObligation", back_populates="contract", lazy="selectin"
    )


class PerformanceObligation(Base):
    __tablename__ = "performance_obligations"
    __table_args__ = ({"schema": "revrec"},)
    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    contract_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("revrec.contracts.id"), nullable=False
    )
    description: Mapped[str] = mapped_column(String, nullable=False)
    pattern: Mapped[str] = mapped_column(String, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    total_amount_cents: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    currency: Mapped[str] = mapped_column(String, nullable=False, default="USD")
    deferred_revenue_account_code: Mapped[str] = mapped_column(String, nullable=False)
    revenue_account_code: Mapped[str] = mapped_column(String, nullable=False)
    units_total: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    unit_label: Mapped[str | None] = mapped_column(String, nullable=True)
    external_ref: Mapped[str | None] = mapped_column(String, nullable=True, unique=True)
    price_per_unit_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    unbilled_ar_account_code: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="1500-UNBILLED-AR",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    contract: Mapped["Contract"] = relationship("Contract", back_populates="obligations")


class RecognitionRun(Base):
    __tablename__ = "recognition_runs"
    __table_args__ = ({"schema": "revrec"},)
    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    run_through_date: Mapped[date] = mapped_column(Date, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    obligations_processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_recognized_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    journal_entry_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("ledger.journal_entries.id"), nullable=True
    )


class RecognitionEvent(Base):
    __tablename__ = "recognition_events"
    __table_args__ = ({"schema": "revrec"},)
    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("revrec.recognition_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    obligation_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("revrec.performance_obligations.id"), nullable=False
    )
    recognized_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    recognized_through: Mapped[date] = mapped_column(Date, nullable=False)


class UsageEvent(Base):
    __tablename__ = "usage_events"
    __table_args__ = ({"schema": "revrec"},)
    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    obligation_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("revrec.performance_obligations.id"), nullable=False
    )
    units: Mapped[int] = mapped_column(BigInteger, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    source: Mapped[str] = mapped_column(String, nullable=False)
    source_event_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("inbox.source_events.id"), nullable=True
    )
    recognized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    recognition_run_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("revrec.recognition_runs.id"), nullable=True
    )


class PaygReclassification(Base):
    __tablename__ = "payg_reclassifications"
    __table_args__ = ({"schema": "revrec"},)
    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    obligation_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("revrec.performance_obligations.id"), nullable=False
    )
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    invoice_external_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    billed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"),
    )
    journal_entry_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("ledger.journal_entries.id"), nullable=False
    )
    source_event_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("inbox.source_events.id"), nullable=True
    )
