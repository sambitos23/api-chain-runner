"""ResultLogger — logs every API call to CSV or Excel."""

from __future__ import annotations

import csv
import dataclasses
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from api_chain_runner.models import LogEntry

COLUMNS = [
    "timestamp",
    "step_name",
    "method",
    "url",
    "request_headers",
    "request_body",
    "status_code",
    "response_body",
    "duration_ms",
    "error",
]


class ResultLogger:
    """Logs every API call to a CSV or Excel file.

    Parameters
    ----------
    output_path:
        Destination file path (e.g. ``"results.csv"``).
    fmt:
        Output format — ``"csv"`` or ``"xlsx"``.
    """

    def __init__(self, output_path: str, fmt: str = "csv") -> None:
        if fmt not in ("csv", "xlsx"):
            raise ValueError(f"Unsupported format '{fmt}'. Must be 'csv' or 'xlsx'.")
        self._output_path = Path(output_path)
        self._fmt = fmt
        self._entries: list[LogEntry] = []

    def log(self, entry: LogEntry) -> None:
        """Append a log entry for a single API call."""
        self._entries.append(entry)

    def finalize(self) -> None:
        """Flush all accumulated entries to the output file."""
        if self._fmt == "csv":
            self._write_csv()
        else:
            self._write_xlsx()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _entry_to_row(self, entry: LogEntry) -> list[str]:
        """Convert a LogEntry to a list of string values matching COLUMNS order."""
        d = dataclasses.asdict(entry)
        return [str(d[col]) if d[col] is not None else "" for col in COLUMNS]

    def _write_csv(self) -> None:
        self._output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._output_path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(COLUMNS)
            for entry in self._entries:
                writer.writerow(self._entry_to_row(entry))

    def _write_xlsx(self) -> None:
        try:
            from openpyxl import Workbook
        except ImportError as exc:
            raise ImportError(
                "openpyxl is required for Excel output. Install it with: pip install openpyxl"
            ) from exc

        wb = Workbook()
        ws = wb.active
        ws.title = "API Results"
        ws.append(COLUMNS)
        for entry in self._entries:
            ws.append(self._entry_to_row(entry))

        self._output_path.parent.mkdir(parents=True, exist_ok=True)
        wb.save(str(self._output_path))
