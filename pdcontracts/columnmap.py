"""Infer which columns of an unknown table mean what.

Every jurisdiction names its contract columns differently. Chicago has
``end_date``, Baltimore has ``contract_expiration``, a FOIA spreadsheet has
``Term Thru``. Rather than hand-maintain a mapping per portal, score each
column name against patterns and take the best match.

Scoring is name-based first, with a value-shape tiebreak: a column that claims
to be a date but holds no parseable dates loses to one that does.
"""

from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .normalize import parse_date, parse_money

# field -> (regex, weight). Higher weight wins ties. Ordered strongest-first.
PATTERNS: Dict[str, List[Tuple[str, int]]] = {
    "end_date": [
        (r"^(contract[_ ]?)?(end|expiration|expiry|expire)[_ ]?date$", 100),
        (r"(expiration|expires|expiry)", 90),
        (r"(end|thru|through|term)[_ ]?date", 80),
        (r"term[_ ]?(thru|through|end)", 85),
        (r"(thru|through)", 75),
        (r"^(contract[_ ]?)?end$", 70),
        (r"period.*end", 65),
        (r"termination[_ ]?date", 60),
    ],
    "start_date": [
        (r"^(contract[_ ]?)?(start|begin|effective|commence)[_ ]?date$", 100),
        (r"(effective|commencement)", 85),
        (r"(start|begin)[_ ]?date", 80),
        (r"^(contract[_ ]?)?start$", 70),
        (r"period.*(start|begin)", 65),
        (r"award[_ ]?date", 50),
    ],
    "vendor": [
        (r"^(vendor|supplier|contractor|payee)([_ ]?name)?$", 100),
        (r"(vendor|supplier|contractor|payee|company)[_ ]?name", 95),
        (r"(vendor|supplier|contractor|payee)", 80),
        (r"legal[_ ]?name", 60),
        (r"^name$", 30),
    ],
    "description": [
        (r"^(contract[_ ]?)?(description|purpose|scope)$", 100),
        (r"(description|purpose)", 90),
        (r"scope[_ ]?of[_ ]?(work|service)", 90),
        (r"(short|long)[_ ]?(desc|title)", 75),
        (r"(commodity|service)[_ ]?(desc|type|category)", 70),
        (r"(title|subject|summary)", 55),
    ],
    "agency": [
        (r"^(department|agency|bureau|division|dept)([_ ]?name)?$", 100),
        (r"(department|agency|bureau)[_ ]?(name|desc)", 95),
        (r"(using|requesting|owner)[_ ]?(dept|department|agency)", 90),
        (r"(department|agency|dept)", 75),
        (r"customer", 40),
    ],
    "total_value": [
        (r"^(contract|award|total)[_ ]?(value|amount|price)$", 100),
        (r"(maximum|max|not[_ ]?to[_ ]?exceed|nte)[_ ]?(amount|value)", 95),
        (r"(total|award|contract)[_ ]?(amount|value)", 90),
        (r"(amount|value|price)", 60),
    ],
    "annual_value": [
        (r"(annual|yearly|per[_ ]?year)[_ ]?(amount|value|cost|spend)", 100),
        (r"(annual|yearly)", 70),
    ],
    "contract_number": [
        (r"^(contract|po|purchase[_ ]?order|award)[_ ]?(number|no|id|#)$", 100),
        (r"(contract|solicitation|award)[_ ]?(number|no|id)", 90),
        (r"^(id|number)$", 40),
    ],
    "state": [
        (r"^(state|st)$", 100),
        (r"state[_ ]?(code|abbr|name)", 90),
    ],
    "renewal_options": [
        (r"(renewal|option)[_ ]?(years?|terms?|periods?|count)", 100),
        (r"(renewals?|options?)", 70),
    ],
}

DATE_FIELDS = {"start_date", "end_date"}
MONEY_FIELDS = {"total_value", "annual_value"}


def _name_score(column: str, field: str) -> int:
    normalized = re.sub(r"[^a-z0-9]+", "_", column.lower()).strip("_")
    best = 0
    for pattern, weight in PATTERNS[field]:
        if re.search(pattern, normalized):
            best = max(best, weight)
    return best


def _value_bonus(field: str, values: Sequence) -> int:
    """Reward columns whose contents match the expected shape."""
    sample = [v for v in values if v not in (None, "")][:40]
    if not sample:
        return 0
    if field in DATE_FIELDS:
        hits = sum(1 for v in sample if parse_date(v) is not None)
        ratio = hits / len(sample)
        return 25 if ratio > 0.7 else (-40 if ratio < 0.2 else 0)
    if field in MONEY_FIELDS:
        hits = sum(1 for v in sample if parse_money(v) is not None)
        ratio = hits / len(sample)
        return 20 if ratio > 0.7 else (-40 if ratio < 0.2 else 0)
    return 0


def map_columns(
    columns: Iterable[str],
    rows: Optional[Sequence[dict]] = None,
    overrides: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    """Map logical field -> actual column name.

    ``overrides`` pins a field to a column and skips inference for it, which is
    how a portal-specific config corrects a bad guess.
    """
    columns = list(columns)
    rows = rows or []
    overrides = overrides or {}
    mapping: Dict[str, str] = {}
    taken = set()

    for field, column in overrides.items():
        if column in columns:
            mapping[field] = column
            taken.add(column)

    scored: List[Tuple[int, str, str]] = []
    for field in PATTERNS:
        if field in mapping:
            continue
        for column in columns:
            if column in taken:
                continue
            score = _name_score(column, field)
            if score <= 0:
                continue
            if rows:
                score += _value_bonus(field, [r.get(column) for r in rows])
            if score > 0:
                scored.append((score, field, column))

    # Greedy assignment, highest-scoring pairs first. One column per field and
    # one field per column, so a single "amount" column cannot be claimed as
    # both total and annual value.
    scored.sort(key=lambda t: (-t[0], t[1], t[2]))
    for score, field, column in scored:
        if field in mapping or column in taken:
            continue
        mapping[field] = column
        taken.add(column)

    return mapping


def describe_mapping(mapping: Dict[str, str]) -> str:
    if not mapping:
        return "no columns mapped"
    return ", ".join(f"{k}<-{v}" for k, v in sorted(mapping.items()))
