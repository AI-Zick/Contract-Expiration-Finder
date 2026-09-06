"""Cleanup helpers for messy government data.

Every public procurement portal formats dates, money, and organization names
differently. These functions collapse that variety into something comparable.
"""

from __future__ import annotations

import datetime as _dt
import re
from typing import Any, Optional

# Corporate suffixes that add nothing to vendor identity.
_VENDOR_NOISE = re.compile(
    r"\b(inc|incorporated|llc|l\.l\.c|llp|lp|ltd|limited|corp|corporation|co|company|"
    r"holdings|group|usa|us|na|intl|international|technologies|technology|tech|"
    r"solutions|systems|services|software|enterprises|and|the)\b",
    re.I,
)
_PUNCT = re.compile(r"[^a-z0-9 ]+")
_WS = re.compile(r"\s+")

# Words that identify a law enforcement agency in a free-text department field.
LE_PATTERNS = [
    r"\bpolice\b",
    r"\bsheriff",
    r"\bpublic safety\b",
    r"\bmarshal",
    r"\bconstable",
    r"\bhighway patrol\b",
    r"\bstate patrol\b",
    r"\bstate troopers?\b",
    r"\blaw enforcement\b",
    r"\bp\.?d\.?\b",
    r"\bs\.?o\.?\b",
]
_LE_RE = re.compile("|".join(LE_PATTERNS), re.I)

# Things that look law-enforcement-ish but are a different buyer with a
# different budget, different decision maker, and usually different software.
LE_EXCLUDE = re.compile(
    r"\b(fire department|fire dept|fire rescue|emergency medical|\bems\b|"
    r"animal control|parking enforcement|code enforcement|"
    r"department of corrections|probation|parole|"
    r"police (and )?fire pension|pension fund|police athletic league|"
    r"crossing guard|transit (authority|district|agency)|"
    r"transportation authority|regional transit)\b",
    re.I,
)

_DATE_FORMATS = [
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%m/%d/%y",
    "%d/%m/%Y",
    "%Y/%m/%d",
    "%m-%d-%Y",
    "%d-%b-%Y",
    "%d-%b-%y",
    "%b %d, %Y",
    "%B %d, %Y",
    "%b %d %Y",
    "%B %d %Y",
    "%Y%m%d",
    "%m/%d/%Y %H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
]

STATE_ABBR = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN",
    "mississippi": "MS", "missouri": "MO", "montana": "MT", "nebraska": "NE",
    "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ",
    "new mexico": "NM", "new york": "NY", "north carolina": "NC",
    "north dakota": "ND", "ohio": "OH", "oklahoma": "OK", "oregon": "OR",
    "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
    "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
    "district of columbia": "DC", "puerto rico": "PR",
}


def parse_date(value: Any) -> Optional[_dt.date]:
    """Parse a date from anything a procurement portal might emit."""
    if value is None or value == "":
        return None
    if isinstance(value, _dt.datetime):
        return value.date()
    if isinstance(value, _dt.date):
        return value
    s = str(value).strip()
    if not s or s.lower() in {"n/a", "na", "none", "null", "-", "tbd", "ongoing"}:
        return None
    # Socrata floating timestamps: 2027-06-30T00:00:00.000
    if "T" in s:
        s = s.split("T", 1)[0]
    for fmt in _DATE_FORMATS:
        try:
            return _dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    # Bare year -- assume end of the calendar year, which is the safer
    # assumption for an expiration date than January 1.
    if re.fullmatch(r"(19|20)\d{2}", s):
        return _dt.date(int(s), 12, 31)
    return None


def parse_money(value: Any) -> Optional[float]:
    """Parse a dollar amount. Returns None rather than guessing at garbage."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    s = str(value).strip()
    if not s:
        return None
    negative = s.startswith("(") and s.endswith(")")
    s = re.sub(r"[,$\s()]", "", s)
    if not s or s.lower() in {"n/a", "na", "none", "null", "-"}:
        return None
    try:
        amount = float(s)
    except ValueError:
        return None
    return -amount if negative else amount


def normalize_vendor_name(name: str) -> str:
    """Collapse a vendor name to a comparable key.

    'Axon Enterprise, Inc.' and 'AXON ENTERPRISE INC' both become 'axon
    enterprise'.
    """
    if not name:
        return ""
    s = name.lower()
    s = s.replace("&", " and ")
    s = _PUNCT.sub(" ", s)
    s = _VENDOR_NOISE.sub(" ", s)
    s = _WS.sub(" ", s).strip()
    return s


def normalize_agency_name(name: str) -> str:
    """Collapse an agency name to a comparable key."""
    if not name:
        return ""
    s = name.lower()
    s = _PUNCT.sub(" ", s)
    s = re.sub(r"\bdept\b", "department", s)
    s = re.sub(r"\bpd\b", "police department", s)
    s = re.sub(r"\bso\b", "sheriffs office", s)
    s = re.sub(r"\bsheriff s\b", "sheriffs", s)
    s = re.sub(r"\bcity of\b|\bcounty of\b|\btown of\b|\bvillage of\b", " ", s)
    s = _WS.sub(" ", s).strip()
    return s


def normalize_state(value: Any) -> str:
    """Return a two-letter state code, or '' if it cannot be determined."""
    if not value:
        return ""
    s = str(value).strip()
    if len(s) == 2 and s.isalpha():
        return s.upper()
    return STATE_ABBR.get(s.lower(), "")


def looks_like_law_enforcement(*texts: str) -> bool:
    """True when the text identifies a law enforcement buyer.

    Checked against every field that might carry the buyer's name -- department,
    agency, division, and the contract description itself, since some portals
    only mention the department in the description.
    """
    blob = " ".join(t for t in texts if t)
    if not blob:
        return False
    if LE_EXCLUDE.search(blob):
        # A combined "Police & Fire" record is still a police record.
        if not re.search(r"\bpolice\b|\bsheriff", blob, re.I):
            return False
    return bool(_LE_RE.search(blob))


def is_non_police_buyer(name: str) -> bool:
    """True when a buyer name is a known adjacent-but-different agency.

    Fire departments, transit districts and pension funds buy software that
    reads like police software. This is a hard exclusion, independent of who
    funded the purchase -- except where the name itself says police or sheriff,
    which is how transit police departments stay in scope.
    """
    if not name:
        return False
    if re.search(r"\bpolice\b|\bsheriff", name, re.I):
        return False
    return bool(LE_EXCLUDE.search(name))


def parse_bool(value: Any) -> Optional[bool]:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    s = str(value).strip().lower()
    if s in {"y", "yes", "true", "t", "1"}:
        return True
    if s in {"n", "no", "false", "f", "0"}:
        return False
    return None


def parse_int(value: Any) -> Optional[int]:
    amount = parse_money(value)
    if amount is None:
        return None
    try:
        return int(amount)
    except (ValueError, OverflowError):
        return None


def clean_text(value: Any, limit: int = 600) -> str:
    if value is None:
        return ""
    s = _WS.sub(" ", str(value)).strip()
    return s[:limit]
