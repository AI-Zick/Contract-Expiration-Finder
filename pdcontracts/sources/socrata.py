"""Socrata (SODA) connector -- the workhorse for city and state contract data.

Hundreds of governments publish contract registers on Socrata, all behind the
same API shape:

    https://<domain>/resource/<dataset_id>.json?$limit=1000&$offset=0

Column names differ wildly between portals, so this connector samples the
dataset, infers the mapping with columnmap, then pages through applying a
server-side filter for law-enforcement departments where possible.

Dataset IDs are NOT hardcoded. ``discover()`` queries the Socrata catalog at
runtime to find contract datasets on a domain, so the config only has to list
domains. Once a dataset is confirmed useful, pin it in config to skip discovery.
"""

from __future__ import annotations

import datetime as _dt
from typing import Dict, List, Optional

from ..classify import classify
from ..columnmap import map_columns
from ..models import Contract
from ..normalize import (
    clean_text,
    looks_like_law_enforcement,
    normalize_state,
    parse_date,
    parse_int,
    parse_money,
)
from .base import FetchError, Source, SourceResult, register

CATALOG_URL = "https://api.us.socrata.com/api/catalog/v1"
PAGE_SIZE = 1000
# Terms used to find contract-like datasets and to filter rows to police buyers.
DATASET_QUERY = "contracts"
LE_FILTER_TERMS = ["POLICE", "SHERIFF", "PUBLIC SAFETY"]


@register
class SocrataSource(Source):
    id = "socrata"
    label = "Socrata open data portal"
    default_confidence = 0.75

    def __init__(self, config=None, fetcher=None):
        super().__init__(config, fetcher)
        self.domain: str = self.config.get("domain", "")
        self.dataset: str = self.config.get("dataset", "")
        self.state: str = normalize_state(self.config.get("state", ""))
        self.jurisdiction: str = self.config.get("jurisdiction", "")
        self.overrides: Dict[str, str] = self.config.get("columns", {}) or {}
        self.app_token: str = self.config.get("app_token", "")
        self.max_rows: int = int(self.config.get("max_rows", 50000))
        # Some portals publish a contract register that is already police-only.
        self.assume_law_enforcement: bool = bool(
            self.config.get("assume_law_enforcement", False)
        )

    # --- discovery --------------------------------------------------------

    def discover(self, limit: int = 20) -> List[dict]:
        """Find candidate contract datasets on this domain."""
        params = {
            "q": DATASET_QUERY,
            "domains": self.domain,
            "search_context": self.domain,
            "limit": limit,
            "only": "dataset",
        }
        payload = self.fetcher.get_json(CATALOG_URL, params=params)
        results = []
        for item in payload.get("results", []):
            resource = item.get("resource", {})
            results.append(
                {
                    "domain": self.domain,
                    "dataset": resource.get("id", ""),
                    "name": resource.get("name", ""),
                    "description": clean_text(resource.get("description", ""), 200),
                    "updated": resource.get("updatedAt", ""),
                    "columns": resource.get("columns_field_name", []),
                }
            )
        return results

    # --- fetching ---------------------------------------------------------

    def _url(self) -> str:
        return f"https://{self.domain}/resource/{self.dataset}.json"

    def _headers(self) -> dict:
        return {"X-App-Token": self.app_token} if self.app_token else {}

    def _fetch_page(self, limit: int, offset: int, where: Optional[str] = None) -> List[dict]:
        params = {"$limit": limit, "$offset": offset, "$order": ":id"}
        if where:
            params["$where"] = where
        return self.fetcher.get_json(self._url(), params=params, headers=self._headers())

    def _le_where_clause(self, agency_column: Optional[str]) -> Optional[str]:
        """Push the police filter to the server when we know the buyer column.

        Large citywide registers can hold 100k+ rows; filtering server-side
        turns a long crawl into one or two pages.
        """
        if not agency_column:
            return None
        clauses = [
            f"upper({agency_column}) like '%{term}%'" for term in LE_FILTER_TERMS
        ]
        return " OR ".join(clauses)

    def check(self) -> SourceResult:
        try:
            rows = self._fetch_page(1, 0)
        except FetchError as exc:
            return SourceResult(status="error", message=str(exc), dataset=self.dataset)
        if not rows:
            return SourceResult(status="empty", message="dataset returned no rows",
                                dataset=self.dataset)
        mapping = map_columns(rows[0].keys(), rows, self.overrides)
        missing = [f for f in ("vendor", "end_date") if f not in mapping]
        status = "ok" if not missing else "partial"
        message = f"columns: {sorted(rows[0].keys())[:12]}"
        if missing:
            message = f"missing {missing}; " + message
        return SourceResult(status=status, message=message, dataset=self.dataset)

    def collect(self, **kwargs) -> SourceResult:
        if not (self.domain and self.dataset):
            return SourceResult(status="error", message="domain and dataset required")

        try:
            sample = self._fetch_page(200, 0)
        except FetchError as exc:
            return SourceResult(status="error", message=str(exc), dataset=self.dataset)
        if not sample:
            return SourceResult(status="empty", message="no rows", dataset=self.dataset)

        mapping = map_columns(sample[0].keys(), sample, self.overrides)
        if "vendor" not in mapping:
            return SourceResult(
                status="error",
                message=f"could not identify a vendor column in {sorted(sample[0].keys())}",
                dataset=self.dataset,
            )

        where = self._le_where_clause(mapping.get("agency"))
        rows: List[dict] = []
        offset = 0
        try:
            while offset < self.max_rows:
                page = self._fetch_page(PAGE_SIZE, offset, where)
                if not page:
                    break
                rows.extend(page)
                if len(page) < PAGE_SIZE:
                    break
                offset += PAGE_SIZE
        except FetchError as exc:
            if not rows:
                return SourceResult(status="error", message=str(exc), dataset=self.dataset)
            # Partial data still beats nothing; report what happened.
            return SourceResult(
                contracts=self.parse_rows(rows, mapping),
                fetched=len(rows),
                status="partial",
                message=f"stopped early: {exc}",
                dataset=self.dataset,
            )

        contracts = self.parse_rows(rows, mapping)
        return SourceResult(
            contracts=contracts,
            fetched=len(rows),
            status="ok",
            message=f"mapped {len(mapping)} columns; kept {len(contracts)} of {len(rows)} rows",
            dataset=self.dataset,
        )

    # --- parsing ----------------------------------------------------------

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

            agency_name = agency_text or self.jurisdiction or self.domain
            if self.jurisdiction and self.jurisdiction.lower() not in agency_name.lower():
                # "Police Department" alone is ambiguous nationally; qualify it.
                agency_name = f"{self.jurisdiction} {agency_name}".strip()

            result = classify(vendor, description)

            contract = Contract(
                agency_name=agency_name,
                vendor_raw=vendor,
                state=normalize_state(field("state")) or self.state,
                vendor_canonical=result.vendor_canonical,
                description=description,
                start_date=parse_date(field("start_date")),
                end_date=parse_date(field("end_date")),
                renewal_options=parse_int(field("renewal_options")),
                total_value=parse_money(field("total_value")),
                annual_value=parse_money(field("annual_value")),
                category=result.category,
                is_software=result.is_software,
                classification_confidence=result.confidence,
                contract_number=clean_text(field("contract_number"), 80),
                source=self.id,
                source_url=f"https://{self.domain}/d/{self.dataset}",
                source_dataset=f"{self.domain}/{self.dataset}",
                retrieved_at=today,
                data_confidence=self.default_confidence,
                raw=row,
            )
            out.append(contract)
        return out
