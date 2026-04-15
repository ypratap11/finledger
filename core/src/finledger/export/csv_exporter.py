import csv
import hashlib
from collections import defaultdict
from pathlib import Path
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from finledger.models.inbox import SourceEvent
from finledger.models.ledger import Account, JournalEntry, JournalLine
from finledger.export.base import DateRange, ExportIntegrityError, ExportResult

SOURCE_REFS_MAX = 1024


class CsvJournalExporter:
    name = "csv"

    def __init__(self, session: AsyncSession):
        self.session = session

    async def export(self, period: DateRange, out_dir: Path) -> ExportResult:
        out_dir.mkdir(parents=True, exist_ok=True)
        file_path = out_dir / f"journal_{period.start}_{period.end}_{self.name}.csv"

        # Fetch lines joined with account + entry + (optional) source_event for the period.
        rows = (await self.session.execute(
            select(
                JournalEntry.posted_at,
                Account.code,
                Account.name,
                JournalLine.side,
                JournalLine.amount_cents,
                JournalLine.currency,
                SourceEvent.external_id,
            )
            .join(JournalLine, JournalLine.entry_id == JournalEntry.id)
            .join(Account, Account.id == JournalLine.account_id)
            .join(SourceEvent, SourceEvent.id == JournalEntry.source_event_id, isouter=True)
            .where(
                text("CAST(journal_entries.posted_at AS DATE) BETWEEN :s AND :e")
            )
            .params(s=period.start, e=period.end)
            .order_by(JournalEntry.posted_at, Account.code)
        )).all()

        # Aggregate by (posting_date, account_code, currency).
        groups: dict[tuple, dict] = defaultdict(
            lambda: {"account_name": "", "debit": 0, "credit": 0, "count": 0, "refs": []}
        )
        for posted_at, code, acc_name, side, amt, ccy, ext_id in rows:
            key = (posted_at.date(), code, ccy)
            g = groups[key]
            g["account_name"] = acc_name
            if side == "debit":
                g["debit"] += amt
            else:
                g["credit"] += amt
            g["count"] += 1
            if ext_id and ext_id not in g["refs"]:
                g["refs"].append(ext_id)

        total_debit = sum(g["debit"] for g in groups.values())
        total_credit = sum(g["credit"] for g in groups.values())
        if total_debit != total_credit:
            raise ExportIntegrityError(
                f"debits ({total_debit}) != credits ({total_credit}) for period {period.start}..{period.end}"
            )

        written = False
        try:
            with file_path.open("w", newline="", encoding="utf-8") as f:
                w = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
                w.writerow([
                    "posting_date", "account_code", "account_name",
                    "debit", "credit", "currency", "entry_count", "source_refs",
                ])
                for (posting_date, code, ccy), g in sorted(groups.items()):
                    refs = ",".join(g["refs"])
                    if len(refs) > SOURCE_REFS_MAX:
                        refs = refs[:SOURCE_REFS_MAX - 3] + "..."
                    w.writerow([
                        posting_date.isoformat(), code, g["account_name"],
                        g["debit"], g["credit"], ccy, g["count"], refs,
                    ])
            written = True

            checksum = hashlib.sha256(file_path.read_bytes()).hexdigest()
            entries_count = sum(g["count"] for g in groups.values())

            result = await self.session.execute(
                text(
                    "INSERT INTO gl.export_runs "
                    "(exporter, period_start, period_end, file_path, checksum, entries_count) "
                    "VALUES (:exporter, :ps, :pe, :fp, :cs, :n) RETURNING id"
                ),
                {
                    "exporter": self.name,
                    "ps": period.start,
                    "pe": period.end,
                    "fp": str(file_path),
                    "cs": checksum,
                    "n": entries_count,
                },
            )
            run_id = result.scalar_one()
            await self.session.flush()
        except Exception:
            if written and file_path.exists():
                file_path.unlink()
            raise

        return ExportResult(
            exporter=self.name,
            period=period,
            entries_exported=entries_count,
            file_path=file_path,
            checksum=checksum,
            run_id=run_id,
        )
