"""Legistar connector -- city council agendas and minutes.

This is the highest-yield source for RMS, CAD and MDT specifically, and it is
worth understanding why. Those systems cost millions and run five to seven
years, which in almost every city puts them over the threshold that requires a
public council vote. So the contract surfaces as a council agenda item months
before it appears in any contract register:

    "Resolution authorizing a five-year agreement with Tyler Technologies for
     a police records management system in an amount not to exceed $2,450,000"

That one line carries the vendor, the term, the value, and a date -- everything
the pitch engine needs. Better still, it is a *leading* indicator: the item
appears when the deal is being approved, not after it lands in an annual data
release, and agendas for upcoming meetings are published before the vote.

Legistar (Granicus) runs the agenda system for several hundred US cities and
counties and exposes a public read API with no key:

    https://webapi.legistar.com/v1/<client>/matters

``client`` is the city's Legistar slug -- 'chicago', 'seattle', 'philadelphia'.
Find it in the URL of a city's public "Legislation" portal.
"""

from __future__ import annotations

import datetime as _dt
import re
from typing import Dict, List, Optional

from ..classify import classify, match_vendor_in_text
from ..fiscal import add_months
from ..models import Contract
from ..normalize import clean_text, looks_like_law_enforcement, normalize_state, parse_date
from ..taxonomy import CATEGORIES
from .base import FetchError, Source, SourceResult, register

API = "https://webapi.legistar.com/v1"
PAGE = 1000

# Only the fields the parser reads. Legistar matters carry a dozen large free
# text fields (MatterEXText1..10) that dwarf everything else; selecting the
# columns we need turns a multi-megabyte page into a small one.
SELECT = ",".join([
    "MatterId", "MatterFile", "MatterName", "MatterTitle", "MatterBodyName",
    "MatterIntroDate", "MatterAgendaDate", "MatterPassedDate",
])

# Phrases that identify a public-safety software item in a resolution title.
MATTER_KEYWORDS = [
    "records management", "computer aided dispatch", "computer-aided dispatch",
    "mobile data", "field reporting", "public safety software", "police software",
    "cad/rms", "cad rms", "dispatch system", "law enforcement software",
]

# "a five-year agreement", "5 year term", "three (3) year"
_TERM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
               "seven": 7, "eight": 8, "nine": 9, "ten": 10}
_TERM_RE = re.compile(
    r"\b(?:(\d{1,2})|(" + "|".join(_TERM_WORDS) + r"))[\s-]*(?:\(\d{1,2}\)[\s-]*)?year",
    re.I,
)
_MONEY_RE = re.compile(r"\$\s?([\d,]+(?:\.\d{2})?)")
_RENEWAL_RE = re.compile(r"(\d{1,2}|" + "|".join(_TERM_WORDS) +
                         r")\s*(?:additional|option|renewal)", re.I)


def extract_term_months(text: str) -> Optional[int]:
    """Pull a contract length out of a resolution title."""
    match = _TERM_RE.search(text or "")
    if not match:
        return None
    years = int(match.group(1)) if match.group(1) else _TERM_WORDS[match.group(2).lower()]
    return years * 12 if 0 < years <= 25 else None


def extract_amount(text: str) -> Optional[float]:
    """Largest dollar figure in the title -- resolutions lead with the ceiling."""
    values = []
    for raw in _MONEY_RE.findall(text or ""):
        try:
            values.append(float(raw.replace(",", "")))
        except ValueError:
            continue
    return max(values) if values else None


def extract_renewals(text: str) -> Optional[int]:
    match = _RENEWAL_RE.search(text or "")
    if not match:
        return None
    token = match.group(1).lower()
    return int(token) if token.isdigit() else _TERM_WORDS.get(token)


@register
class LegistarSource(Source):
    id = "legistar"
    label = "Legistar council agendas"
    # Council items state terms and ceilings explicitly, but the start date is
    # the approval date rather than the executed contract date, so the derived
    # expiration is a close estimate rather than a certainty.
    default_confidence = 0.65

    def __init__(self, config=None, fetcher=None):
        super().__init__(config, fetcher)
        self.client: str = self.config.get("client", "")
        self.state: str = normalize_state(self.config.get("state", ""))
        self.jurisdiction: str = self.config.get("jurisdiction", "")
        self.years_back: int = int(self.config.get("years_back", 8))
        self.max_pages: int = int(self.config.get("max_pages", 12))
        self.keywords: List[str] = self.config.get("keywords") or list(MATTER_KEYWORDS)

    def _url(self, path: str) -> str:
        return f"{API}/{self.client}/{path}"

    def check(self) -> SourceResult:
        try:
            rows = self.fetcher.get_json(self._url("bodies"), params={"$top": 1})
        except FetchError as exc:
            return SourceResult(status="error", message=str(exc), dataset=self.client)
        return SourceResult(
            status="ok" if rows else "empty",
            message=f"legistar client '{self.client}' reachable",
            dataset=self.client,
        )

    def _keyword_filter(self) -> str:
        """OData clause matching any keyword, case-insensitively.

        Council titles are inconsistently cased, so both sides are lowered.
        """
        clauses = [
            f"substringof('{k.replace(chr(39), chr(39) * 2)}',tolower(MatterTitle))"
            for k in self.keywords
        ]
        return "(" + " or ".join(clauses) + ")"

    def _page(self, page: int, where: str) -> List[dict]:
        params = {
            "$top": PAGE,
            "$skip": page * PAGE,
            "$orderby": "MatterIntroDate desc",
            "$select": SELECT,
            "$filter": where,
        }
        return self.fetcher.get_json(self._url("matters"), params=params)

    def _fetch(self) -> List[dict]:
        """Fetch matching matters, filtering server-side where possible.

        Pulling every matter and filtering locally means downloading years of a
        city's entire legislative history to find a handful of contract items.
        Legistar's OData supports substringof, so the keyword test is pushed to
        the server; if a deployment rejects that, fall back to the date filter
        alone rather than losing the source.
        """
        since = _dt.date.today().replace(year=_dt.date.today().year - self.years_back)
        date_clause = f"MatterIntroDate gt datetime'{since.isoformat()}'"

        for where in (f"{date_clause} and {self._keyword_filter()}", date_clause):
            rows: List[dict] = []
            try:
                for page in range(self.max_pages):
                    batch = self._page(page, where)
                    if not batch:
                        break
                    rows.extend(batch)
                    if len(batch) < PAGE:
                        break
                return rows
            except FetchError:
                continue  # server rejected the filter; try the broader one
        raise FetchError(f"legistar '{self.client}' rejected both queries")

    def collect(self, **kwargs) -> SourceResult:
        if not self.client:
            return SourceResult(status="error", message="legistar 'client' slug required")
        try:
            rows = self._fetch()
        except FetchError as exc:
            return SourceResult(status="error", message=str(exc), dataset=self.client)
        if not rows:
            return SourceResult(status="empty", message="no matters returned",
                                dataset=self.client)
        contracts = self.parse_rows(rows)
        return SourceResult(
            contracts=contracts,
            fetched=len(rows),
            status="ok",
            message=f"scanned {len(rows)} council items; kept {len(contracts)}",
            dataset=self.client,
        )

    def parse_rows(self, rows: List[dict]) -> List[Contract]:
        out: List[Contract] = []
        today = _dt.date.today()
        seen = set()

        for row in rows:
            title = clean_text(
                row.get("MatterTitle") or row.get("MatterName") or "", 1200
            )
            if not title:
                continue
            low = title.lower()
            if not any(k in low for k in self.keywords):
                continue
            body = clean_text(row.get("MatterBodyName") or "", 120)
            # Either the sponsoring body or the item text has to point at police.
            if not looks_like_law_enforcement(body, title):
                continue

            # The vendor is named inside the resolution text, not in a field.
            _, vendor_name = match_vendor_in_text(title)
            result = classify(vendor_name, title)
            if not result.category:
                continue

            approved = (
                parse_date(row.get("MatterPassedDate"))
                or parse_date(row.get("MatterAgendaDate"))
                or parse_date(row.get("MatterIntroDate"))
            )
            term = extract_term_months(title)
            if not term:
                cat = CATEGORIES.get(result.category)
                term = cat.typical_term_months if cat else 60
            end = add_months(approved, term) if approved else None

            total = extract_amount(title)
            number = clean_text(row.get("MatterFile") or "", 60)
            if number and number in seen:
                continue
            if number:
                seen.add(number)

            agency = self.jurisdiction or self.client
            out.append(
                Contract(
                    agency_name=f"{agency} Police Department".strip(),
                    vendor_raw=result.vendor_canonical or "UNNAMED (see council item)",
                    state=self.state,
                    vendor_canonical=result.vendor_canonical,
                    description=title[:600],
                    start_date=approved,
                    end_date=end,
                    renewal_options=extract_renewals(title),
                    total_value=total,
                    category=result.category,
                    is_software=True,
                    classification_confidence=result.confidence,
                    contract_number=number,
                    source=self.id,
                    source_url=(
                        f"https://{self.client}.legistar.com/LegislationDetail.aspx"
                        f"?ID={row.get('MatterId')}" if row.get("MatterId") else ""
                    ),
                    source_dataset=f"legistar/{self.client}",
                    retrieved_at=today,
                    # Expiration derived from a stated term, not a stated date.
                    data_confidence=self.default_confidence if end else 0.4,
                    raw=row,
                )
            )
        return out
