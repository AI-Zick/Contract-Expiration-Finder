"""Renders the pipeline as an interactive dashboard.

One HTML asset backs three surfaces: the local server (`pdcontracts serve`),
the self-contained export (`pdcontracts report --format html`), and a published
web page. They differ only in the JSON payload injected into the page, so there
is a single UI to maintain.
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .report import Opportunity
from .taxonomy import CATEGORIES

ASSET = Path(__file__).parent / "assets" / "dashboard.html"
PLACEHOLDER = "__PDCONTRACTS_DATA__"

DOCUMENT = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{head}
</head>
<body>
{body}
</body>
</html>
"""


def _iso(value: Optional[_dt.date]) -> Optional[str]:
    return value.isoformat() if value else None


def opportunity_payload(opp: Opportunity, index: int) -> Dict[str, Any]:
    return {
        "id": index,
        "agency": opp.agency_name,
        "state": opp.state,
        "incumbent": opp.incumbent,
        "categories": opp.categories,
        "categoryLabels": opp.category_labels,
        "annual": opp.annual_value,
        "expires": _iso(opp.earliest_end),
        "pitchOpen": _iso(opp.pitch_open),
        "budgetDeadline": _iso(opp.budget_deadline),
        "stage": opp.stage,
        "priority": opp.priority,
        "action": opp.action,
        "rationale": opp.rationale,
        "sources": opp.sources,
        "contracts": [
            {
                "vendor": t.vendor_canonical,
                "description": t.description,
                "category": CATEGORIES[t.category].label if t.category in CATEGORIES else t.category,
                "end": _iso(t.end_date),
                "annual": t.annual_value,
                "number": t.contract_number,
                "source": t.source,
                "url": t.source_url,
            }
            for t in opp.targets
        ],
    }


def build_payload(
    opportunities: List[Opportunity],
    focus: Optional[List[str]] = None,
    today: Optional[_dt.date] = None,
    sample: bool = False,
    sample_note: str = "",
    contract_count: int = 0,
) -> Dict[str, Any]:
    today = today or _dt.date.today()
    focus = focus or []
    return {
        "generated": today.isoformat(),
        "today": today.isoformat(),
        "focus": focus,
        "focusLabels": [
            CATEGORIES[c].label if c in CATEGORIES else c for c in focus
        ] or ["All categories"],
        "sample": sample,
        "sampleNote": sample_note,
        "contractCount": contract_count or sum(len(o.targets) for o in opportunities),
        "opportunities": [
            opportunity_payload(o, i) for i, o in enumerate(opportunities)
        ],
    }


def _inject(payload: Dict[str, Any]) -> str:
    body = ASSET.read_text(encoding="utf-8")
    # Escaping "<" keeps a stray "</script>" inside any string from ending the
    # data block early; < is valid inside a JSON string and "<" never
    # appears in JSON outside one.
    blob = json.dumps(payload, ensure_ascii=False, default=str).replace("<", "\\u003c")
    return body.replace(PLACEHOLDER, blob)


def render_fragment(payload: Dict[str, Any]) -> str:
    """The page without a document shell, for hosts that supply their own."""
    return _inject(payload)


def render_document(payload: Dict[str, Any]) -> str:
    """A complete, self-contained HTML file."""
    fragment = _inject(payload)
    # Everything up to the first <div class="shell"> belongs in <head>.
    split = fragment.find('<div class="shell">')
    head, body = fragment[:split], fragment[split:]
    return DOCUMENT.format(head=head.strip(), body=body.strip())


def render_dashboard(
    opportunities: List[Opportunity],
    focus: Optional[List[str]] = None,
    today: Optional[_dt.date] = None,
    standalone: bool = True,
    **kwargs,
) -> str:
    payload = build_payload(opportunities, focus, today, **kwargs)
    return render_document(payload) if standalone else render_fragment(payload)
