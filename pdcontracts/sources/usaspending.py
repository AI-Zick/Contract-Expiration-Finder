"""USAspending.gov connector -- federal awards and grants.

Two reasons this matters for a local PD software pipeline even though cities
buy with local money:

1. Federal law enforcement agencies buy directly, and those contracts are here
   in full with period-of-performance end dates.
2. Byrne/JAG and COPS grants to cities frequently fund records-management and
   dispatch upgrades. A city that just took a grant naming "records management"
   is about to run a procurement -- that is a leading indicator, not a lagging
   one, and it appears here months before any local contract register does.

No API key required.
"""

from __future__ import annotations

import datetime as _dt
from typing import List, Optional

from ..classify import classify
from ..models import Contract
from ..normalize import clean_text, normalize_state, parse_date, parse_money
from .base import FetchError, Source, SourceResult, register

API = "https://api.usaspending.gov/api/v2"

# Contract award types (A-D) plus grant types (02-05) so JAG/COPS grants
# funding software show up alongside direct purchases.
CONTRACT_TYPES = ["A", "B", "C", "D"]
GRANT_TYPES = ["02", "03", "04", "05"]

DEFAULT_KEYWORDS = [
    "records management system",
    "computer aided dispatch",
    "mobile data terminal",
    "police records management",
    "law enforcement software",
]

CONTRACT_FIELDS = [
    "Award ID", "Recipient Name", "Start Date", "End Date", "Award Amount",
    "Description", "Awarding Agency", "Awarding Sub Agency",
    "Place of Performance State Code", "generated_internal_id",
]
GRANT_FIELDS = [
    "Award ID", "Recipient Name", "Start Date", "End Date", "Award Amount",
    "Description", "Awarding Agency", "Awarding Sub Agency",
    "Place of Performance State Code", "generated_internal_id",
]


@register
class USASpendingSource(Source):
    id = "usaspending"
    label = "USAspending.gov federal awards"
    default_confidence = 0.85

    def __init__(self, config=None, fetcher=None):
        super().__init__(config, fetcher)
        self.keywords: List[str] = self.config.get("keywords") or list(DEFAULT_KEYWORDS)
        self.include_grants: bool = bool(self.config.get("include_grants", True))
        self.years_back: int = int(self.config.get("years_back", 6))
        self.max_pages: int = int(self.config.get("max_pages", 10))
        self.page_size: int = int(self.config.get("page_size", 100))

    def _time_period(self) -> List[dict]:
        today = _dt.date.today()
        start = today.replace(year=today.year - self.years_back)
        return [{"start_date": start.isoformat(), "end_date": today.isoformat()}]

    def _search(self, keyword: str, award_types: List[str], fields: List[str]) -> List[dict]:
        rows: List[dict] = []
        for page in range(1, self.max_pages + 1):
            payload = {
                "filters": {
                    "keywords": [keyword],
                    "award_type_codes": award_types,
                    "time_period": self._time_period(),
                },
                "fields": fields,
                "page": page,
                "limit": self.page_size,
                "sort": "Award Amount",
                "order": "desc",
                "subawards": False,
            }
            data = self.fetcher.post_json(f"{API}/search/spending_by_award/", payload)
            results = data.get("results", [])
            rows.extend(results)
            if not data.get("page_metadata", {}).get("hasNext"):
                break
        return rows

    def check(self) -> SourceResult:
        try:
            data = self.fetcher.get_json(f"{API}/references/toptier_agencies/")
        except FetchError as exc:
            return SourceResult(status="error", message=str(exc))
        n = len(data.get("results", []))
        return SourceResult(status="ok" if n else "empty",
                            message=f"api reachable, {n} agencies listed")

    def collect(self, **kwargs) -> SourceResult:
        rows: List[dict] = []
        errors: List[str] = []
        for keyword in self.keywords:
            for award_types, fields, kind in [
                (CONTRACT_TYPES, CONTRACT_FIELDS, "contract"),
                (GRANT_TYPES, GRANT_FIELDS, "grant"),
            ]:
                if kind == "grant" and not self.include_grants:
                    continue
                try:
                    for row in self._search(keyword, award_types, fields):
                        row["_kind"] = kind
                        row["_keyword"] = keyword
                        rows.append(row)
                except FetchError as exc:
                    errors.append(f"{keyword}/{kind}: {exc}")

        contracts = self.parse_rows(rows)
        status = "ok" if not errors else ("partial" if contracts else "error")
        return SourceResult(
            contracts=contracts,
            fetched=len(rows),
            status=status,
            message="; ".join(errors) if errors else f"kept {len(contracts)} of {len(rows)}",
            dataset="spending_by_award",
        )

    def parse_rows(self, rows: List[dict]) -> List[Contract]:
        out: List[Contract] = []
        seen = set()
        today = _dt.date.today()
        for row in rows:
            recipient = clean_text(row.get("Recipient Name"), 200)
            if not recipient:
                continue
            award_id = clean_text(row.get("Award ID"), 80)
            if award_id and award_id in seen:
                continue
            if award_id:
                seen.add(award_id)

            description = clean_text(row.get("Description"))
            is_grant = row.get("_kind") == "grant"

            # For a grant the recipient is the buyer (a city), and the vendor is
            # not yet chosen -- that is exactly why it is an early signal.
            if is_grant:
                vendor_raw = "UNAWARDED (grant-funded)"
                result = classify("", description or row.get("_keyword", ""))
                confidence = 0.5
            else:
                vendor_raw = recipient
                result = classify(vendor_raw, description)
                confidence = self.default_confidence

            agency_name = recipient if is_grant else clean_text(
                row.get("Awarding Sub Agency") or row.get("Awarding Agency"), 200
            )
            if not agency_name:
                continue

            out.append(
                Contract(
                    agency_name=agency_name,
                    vendor_raw=vendor_raw,
                    state=normalize_state(row.get("Place of Performance State Code")),
                    vendor_canonical=result.vendor_canonical,
                    description=description,
                    start_date=parse_date(row.get("Start Date")),
                    end_date=parse_date(row.get("End Date")),
                    total_value=parse_money(row.get("Award Amount")),
                    category=result.category,
                    is_software=result.is_software,
                    classification_confidence=result.confidence,
                    contract_number=award_id,
                    source=self.id,
                    source_url=(
                        f"https://www.usaspending.gov/award/{row.get('generated_internal_id')}"
                        if row.get("generated_internal_id") else "https://www.usaspending.gov"
                    ),
                    source_dataset="spending_by_award",
                    retrieved_at=today,
                    data_confidence=confidence,
                    raw=row,
                )
            )
        return out
