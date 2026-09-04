"""Cooperative purchasing vehicles.

Most agencies can skip a competitive RFP entirely by buying off an existing
cooperative master agreement (Sourcewell, NASPO ValuePoint, OMNIA, BuyBoard,
HGACBuy, TIPS). For a challenger this cuts a 12-month procurement to weeks, so
knowing which vehicles you and your competitors hold -- and when those vehicles
expire -- changes what is sellable inside a given budget window.

These are purchasing *vehicles*, not agency contracts, so they are stored with
source='cooperative' and excluded from agency targeting by default. Surface
them with ``pdcontracts vehicles``.

The co-ops publish this on their own sites in inconsistent HTML, so this source
reads a maintained CSV rather than scraping. Refresh it from the co-op contract
search pages; ``pdcontracts vehicles --stale`` flags rows older than 180 days.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import List

from ..models import Contract
from .base import Source, SourceResult, register
from .csvfile import CSVSource

COOPERATIVES = {
    "sourcewell": "Sourcewell",
    "naspo": "NASPO ValuePoint",
    "omnia": "OMNIA Partners",
    "buyboard": "BuyBoard",
    "hgacbuy": "HGACBuy",
    "tips": "TIPS Purchasing",
    "gsa": "GSA Schedule",
}


@register
class CooperativeSource(Source):
    id = "cooperative"
    label = "Cooperative purchasing vehicles"
    default_confidence = 0.8

    def __init__(self, config=None, fetcher=None):
        super().__init__(config, fetcher)
        self.path: str = self.config.get("path", "config/cooperative_contracts.csv")

    def check(self) -> SourceResult:
        exists = Path(self.path).exists()
        return SourceResult(
            status="ok" if exists else "error",
            message=f"{self.path} {'present' if exists else 'missing'}",
        )

    def collect(self, **kwargs) -> SourceResult:
        if not Path(self.path).exists():
            return SourceResult(status="error", message=f"file not found: {self.path}")

        inner = CSVSource(
            {
                "path": self.path,
                "source_name": self.id,
                "assume_law_enforcement": True,
                # The co-op name lives in a column the mapper would not guess.
                "columns": {"agency": "cooperative"},
                "confidence": self.default_confidence,
            }
        )
        result = inner.collect()
        for contract in result.contracts:
            coop = COOPERATIVES.get(
                contract.agency_name.strip().lower(), contract.agency_name
            )
            contract.agency_name = f"{coop} (purchasing vehicle)"
            contract.source = self.id
            contract.state = ""
        result.dataset = Path(self.path).name
        return result
