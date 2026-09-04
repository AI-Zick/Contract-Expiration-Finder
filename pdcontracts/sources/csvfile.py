"""CSV connector -- for everything the APIs cannot reach.

Most of the country's 18,000 law enforcement agencies do not publish machine
readable contract data. What you get instead is a spreadsheet: a public records
response, a state comptroller export, a list bought from a data broker, or
notes typed by a rep after a call. This connector ingests all of them with the
same column inference used for portals, so a FOIA response becomes a ranked
target the moment it lands.
"""

from __future__ import annotations

import csv
import datetime as _dt
import io
from pathlib import Path
from typing import Dict, List, Optional

from ..classify import classify
from ..columnmap import map_columns
from ..models import Contract
from ..normalize import (
    clean_text,
    looks_like_law_enforcement,
    normalize_state,
    parse_bool,
    parse_date,
    parse_int,
    parse_money,
)
from .base import Source, SourceResult, register


@register
class CSVSource(Source):
    id = "csv"
    label = "CSV / spreadsheet import"
    default_confidence = 0.7

    def __init__(self, config=None, fetcher=None):
        super().__init__(config, fetcher)
        self.path: str = self.config.get("path", "")
        self.state: str = normalize_state(self.config.get("state", ""))
        self.jurisdiction: str = self.config.get("jurisdiction", "")
        self.overrides: Dict[str, str] = self.config.get("columns", {}) or {}
        self.source_name: str = self.config.get("source_name", "csv")
        self.source_url: str = self.config.get("source_url", "")
        # FOIA responses are usually already scoped to the PD, so skip the
        # law-enforcement filter unless asked to apply it.
        self.assume_law_enforcement: bool = bool(
            self.config.get("assume_law_enforcement", True)
        )
        self.confidence: float = float(
            self.config.get("confidence", self.default_confidence)
        )

    def check(self) -> SourceResult:
        if not self.path or not Path(self.path).exists():
            return SourceResult(status="error", message=f"file not found: {self.path}")
        return SourceResult(status="ok", message=f"{self.path} readable")

    def collect(self, **kwargs) -> SourceResult:
        text = kwargs.get("text")
        if text is None:
            if not self.path or not Path(self.path).exists():
                return SourceResult(status="error", message=f"file not found: {self.path}")
            text = Path(self.path).read_text(encoding="utf-8-sig", errors="replace")

        rows = list(csv.DictReader(io.StringIO(text)))
        if not rows:
            return SourceResult(status="empty", message="no rows in file")

        mapping = map_columns(rows[0].keys(), rows, self.overrides)
        if "vendor" not in mapping:
            return SourceResult(
                status="error",
                message=f"no vendor column found in {list(rows[0].keys())}; "
                        f"pin one with --column vendor=<name>",
            )

        contracts = self.parse_rows(rows, mapping)
        return SourceResult(
            contracts=contracts,
            fetched=len(rows),
            status="ok",
            message=f"mapped {len(mapping)} columns; kept {len(contracts)} of {len(rows)}",
            dataset=Path(self.path).name if self.path else "inline",
        )

    def parse_rows(self, rows: List[dict], mapping: Dict[str, str]) -> List[Contract]:
        out: List[Contract] = []
        today = _dt.date.today()
        for row in rows:
            def field(name: str):
                column = mapping.get(name)
                return row.get(column) if column else None

            vendor = clean_text(field("vendor"), 200)
            if not vendor:
                continue
            agency_text = clean_text(field("agency"), 200)
            description = clean_text(field("description"))

            if not self.assume_law_enforcement and not looks_like_law_enforcement(
                agency_text, description
            ):
                continue

            agency_name = agency_text or self.jurisdiction
            if not agency_name:
                continue
            if self.jurisdiction and self.jurisdiction.lower() not in agency_name.lower():
                agency_name = f"{self.jurisdiction} {agency_name}".strip()

            result = classify(vendor, description)
            out.append(
                Contract(
                    agency_name=agency_name,
                    vendor_raw=vendor,
                    state=normalize_state(field("state")) or self.state,
                    vendor_canonical=result.vendor_canonical,
                    description=description,
                    start_date=parse_date(field("start_date")),
                    end_date=parse_date(field("end_date")),
                    renewal_options=parse_int(field("renewal_options")),
                    auto_renew=parse_bool(row.get("auto_renew")),
                    total_value=parse_money(field("total_value")),
                    annual_value=parse_money(field("annual_value")),
                    category=result.category,
                    is_software=result.is_software,
                    classification_confidence=result.confidence,
                    contract_number=clean_text(field("contract_number"), 80),
                    source=self.source_name,
                    source_url=self.source_url,
                    source_dataset=Path(self.path).name if self.path else "inline",
                    retrieved_at=today,
                    data_confidence=self.confidence,
                    raw=row,
                )
            )
        return out
