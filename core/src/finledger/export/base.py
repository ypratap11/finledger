from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Protocol


class ExportIntegrityError(Exception):
    """Raised when the aggregated debits do not equal credits for the export period."""


@dataclass(frozen=True)
class DateRange:
    start: date
    end: date


@dataclass(frozen=True)
class ExportResult:
    exporter: str
    period: DateRange
    entries_exported: int
    file_path: Path
    checksum: str
    run_id: int


class JournalExporter(Protocol):
    name: str

    async def export(self, period: DateRange, out_dir: Path) -> ExportResult: ...
