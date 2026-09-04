"""Core data model.

Three record types flow through the system:

    Agency    a law enforcement agency (the buyer)
    Contract  a procurement record, normalized from whatever source produced it
    Target    a derived sales recommendation: which agency, when to pitch, why

Contracts are deliberately tolerant of missing data. Public procurement records
are wildly inconsistent -- many list a vendor and an end date and nothing else.
A record with only those two fields is still actionable, so nothing beyond
``agency_name`` and ``vendor_raw`` is required.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
from dataclasses import dataclass, field, asdict, fields
from typing import Any, Dict, List, Optional


# Fiscal-year start month by state. Most governments run July-June; these are
# the documented exceptions at the state level. Municipalities inside a state
# often differ, which is why Agency carries its own override.
STATE_FISCAL_START = {
    "AL": 10,
    "MI": 10,
    "NY": 4,
    "TX": 9,
}
DEFAULT_FISCAL_START = 7


@dataclass
class Agency:
    """A law enforcement agency."""

    name: str
    state: str = ""
    city: str = ""
    county: str = ""
    # FBI Originating Agency Identifier, when known. Best available national
    # join key for law enforcement agencies.
    ori: str = ""
    agency_type: str = ""          # municipal | county | state | tribal | campus | transit | federal
    sworn_officers: Optional[int] = None
    population_served: Optional[int] = None
    # Month (1-12) the agency's fiscal year begins. None => infer from state.
    fiscal_year_start_month: Optional[int] = None
    website: str = ""
    notes: str = ""

    @property
    def key(self) -> str:
        """Stable identity for dedup and joins."""
        if self.ori:
            return f"ori:{self.ori.upper()}"
        from .normalize import normalize_agency_name

        return f"name:{self.state.upper()}:{normalize_agency_name(self.name)}"

    @property
    def fiscal_start(self) -> int:
        if self.fiscal_year_start_month:
            return self.fiscal_year_start_month
        return STATE_FISCAL_START.get(self.state.upper(), DEFAULT_FISCAL_START)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Agency":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class Contract:
    """A normalized procurement record."""

    agency_name: str
    vendor_raw: str

    state: str = ""
    agency_key: str = ""
    vendor_canonical: str = ""
    description: str = ""

    start_date: Optional[_dt.date] = None
    end_date: Optional[_dt.date] = None
    # Contract extensions the buyer may exercise without re-bidding. These push
    # the real decision point out and matter a lot for pitch timing.
    renewal_options: Optional[int] = None
    auto_renew: Optional[bool] = None

    total_value: Optional[float] = None
    annual_value: Optional[float] = None

    category: str = ""             # from taxonomy: rms, cad, bwc, alpr, ...
    is_software: Optional[bool] = None
    classification_confidence: float = 0.0

    contract_number: str = ""
    source: str = ""               # connector id that produced the record
    source_url: str = ""
    source_dataset: str = ""
    retrieved_at: Optional[_dt.date] = None
    # 0..1 -- how much the numbers can be trusted. Payment-derived records and
    # fuzzy column mappings score lower than an explicit contract register.
    data_confidence: float = 0.5
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def term_months(self) -> Optional[int]:
        if not (self.start_date and self.end_date):
            return None
        months = (self.end_date.year - self.start_date.year) * 12 + (
            self.end_date.month - self.start_date.month
        )
        return max(months, 0)

    @property
    def effective_annual_value(self) -> Optional[float]:
        """Annualized spend, computed from total value and term when needed."""
        if self.annual_value is not None:
            return self.annual_value
        if self.total_value is None:
            return None
        months = self.term_months
        if not months:
            return self.total_value
        return self.total_value * 12.0 / months

    @property
    def fingerprint(self) -> str:
        """Identity used to merge the same contract seen in two sources."""
        from .normalize import normalize_agency_name, normalize_vendor_name

        if self.contract_number:
            base = f"{self.state}|{normalize_agency_name(self.agency_name)}|{self.contract_number.strip().lower()}"
        else:
            base = "|".join(
                [
                    self.state,
                    normalize_agency_name(self.agency_name),
                    normalize_vendor_name(self.vendor_raw),
                    self.end_date.isoformat() if self.end_date else "",
                ]
            )
        return hashlib.sha1(base.encode("utf-8")).hexdigest()[:20]

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        for k in ("start_date", "end_date", "retrieved_at"):
            if d[k] is not None:
                d[k] = d[k].isoformat()
        d["raw"] = json.dumps(self.raw, default=str)
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Contract":
        d = dict(d)
        for k in ("start_date", "end_date", "retrieved_at"):
            v = d.get(k)
            if isinstance(v, str) and v:
                d[k] = _dt.date.fromisoformat(v)
            elif not v:
                d[k] = None
        raw = d.get("raw")
        if isinstance(raw, str):
            try:
                d["raw"] = json.loads(raw) if raw else {}
            except (ValueError, TypeError):
                d["raw"] = {}
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class Target:
    """A ranked sales recommendation derived from a contract."""

    agency_name: str
    state: str
    vendor_canonical: str
    category: str
    end_date: Optional[_dt.date]
    annual_value: Optional[float]

    # When to make first contact, and the date after which the money for the
    # replacement is already locked into a budget.
    pitch_open: Optional[_dt.date] = None
    pitch_close: Optional[_dt.date] = None
    budget_deadline: Optional[_dt.date] = None
    stage: str = ""                # too_early | pitch_now | procurement_live | late | expired | unknown
    priority: float = 0.0
    action: str = ""
    rationale: List[str] = field(default_factory=list)

    contract_fingerprint: str = ""
    source: str = ""
    source_url: str = ""
    data_confidence: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        for k in ("end_date", "pitch_open", "pitch_close", "budget_deadline"):
            if d[k] is not None:
                d[k] = d[k].isoformat()
        return d
