"""Output formats: console, CSV, and a standalone HTML briefing.

Also holds suite grouping. RMS, CAD and MDT are nearly always bought from one
vendor as a single procurement, so showing a rep three separate rows for the
same decision is misleading -- it triples the apparent pipeline and hides the
fact that one displacement wins all three. ``group_opportunities`` collapses
them into one opportunity per agency+incumbent, timed off the earliest
expiration in the group, since that is the date that forces the decision.
"""

from __future__ import annotations

import csv
import datetime as _dt
import io
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .models import Target
from .taxonomy import CATEGORIES

STAGE_ORDER = ["pitch_now", "procurement_live", "too_early", "expired", "late", "unknown"]
STAGE_LABEL = {
    "pitch_now": "Pitch now",
    "procurement_live": "Procurement live",
    "too_early": "Too early - watch",
    "late": "Late",
    "expired": "Past expiration",
    "unknown": "No expiration known",
}


@dataclass
class Opportunity:
    """One buying decision, possibly covering several contracts."""

    agency_name: str
    state: str
    incumbent: str
    categories: List[str] = field(default_factory=list)
    annual_value: Optional[float] = None
    earliest_end: Optional[_dt.date] = None
    pitch_open: Optional[_dt.date] = None
    budget_deadline: Optional[_dt.date] = None
    stage: str = ""
    priority: float = 0.0
    action: str = ""
    rationale: List[str] = field(default_factory=list)
    sources: List[str] = field(default_factory=list)
    targets: List[Target] = field(default_factory=list)

    @property
    def category_labels(self) -> str:
        return ", ".join(
            CATEGORIES[c].label if c in CATEGORIES else (c or "unclassified")
            for c in self.categories
        )


def as_opportunities(targets: List[Target]) -> List[Opportunity]:
    """Wrap each target as its own opportunity, without suite grouping."""
    out = [
        Opportunity(
            agency_name=t.agency_name,
            state=t.state,
            incumbent=t.vendor_canonical,
            categories=[t.category] if t.category else [],
            annual_value=t.annual_value,
            earliest_end=t.end_date,
            pitch_open=t.pitch_open,
            budget_deadline=t.budget_deadline,
            stage=t.stage,
            priority=t.priority,
            action=t.action,
            rationale=list(t.rationale),
            sources=[t.source] if t.source else [],
            targets=[t],
        )
        for t in targets
    ]
    out.sort(key=lambda o: o.priority, reverse=True)
    return out


def group_opportunities(targets: List[Target]) -> List[Opportunity]:
    """Collapse targets into one opportunity per agency + incumbent vendor."""
    buckets: Dict[tuple, List[Target]] = defaultdict(list)
    for target in targets:
        buckets[(target.state, target.agency_name.lower(), target.vendor_canonical.lower())].append(target)

    out: List[Opportunity] = []
    for members in buckets.values():
        # Two different shapes hide in one group, and they need opposite rules.
        #
        # Several systems from one vendor (RMS + CAD + MDT) expire on their own
        # dates, and the earliest forces the decision.
        #
        # One system amended repeatedly -- Denver's fifth, sixth and seventh
        # amendatory agreements with Versaterm all appear as separate council
        # items -- is a single contract whose later amendment supersedes the
        # earlier. Taking the earliest there would time the pitch off a
        # contract that no longer exists.
        #
        # So: collapse each category to its latest expiration first, then take
        # the earliest across categories.
        dated = [m for m in members if m.end_date]
        if dated:
            current_per_category = {}
            for member in dated:
                key = member.category or ""
                seen = current_per_category.get(key)
                if seen is None or member.end_date > seen.end_date:
                    current_per_category[key] = member
            driver = min(current_per_category.values(), key=lambda m: m.end_date)
        else:
            driver = members[0]

        # Value follows the same rule: sum the current contract per category,
        # not every superseded amendment of the same one.
        current = list(current_per_category.values()) if dated else members
        values = [m.annual_value for m in current if m.annual_value]
        opp = Opportunity(
            agency_name=driver.agency_name,
            state=driver.state,
            incumbent=driver.vendor_canonical,
            categories=sorted({m.category for m in current if m.category}),
            annual_value=sum(values) if values else None,
            earliest_end=driver.end_date,
            pitch_open=driver.pitch_open,
            budget_deadline=driver.budget_deadline,
            stage=driver.stage,
            # Priority is the strongest member plus a small bonus for breadth:
            # displacing an incumbent across three systems is worth more than
            # one, but not three times more.
            priority=round(
                max(m.priority for m in members) + 2.0 * (len(members) - 1), 1
            ),
            action=driver.action,
            rationale=list(driver.rationale),
            sources=sorted({m.source for m in members if m.source}),
            targets=members,
        )
        if len(members) > 1:
            opp.rationale.insert(
                0,
                f"{len(members)} contracts with {opp.incumbent} at this agency "
                f"({opp.category_labels}) \u2014 likely one suite decision.",
            )
        out.append(opp)

    out.sort(key=lambda o: o.priority, reverse=True)
    return out


# --- console --------------------------------------------------------------

def _money(value: Optional[float]) -> str:
    if not value:
        return "-"
    if value >= 1_000_000:
        return f"${value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"${value / 1_000:.0f}k"
    return f"${value:.0f}"


def _date(value: Optional[_dt.date]) -> str:
    return value.strftime("%Y-%m-%d") if value else "-"


def console_table(opportunities: List[Opportunity], limit: int = 40) -> str:
    if not opportunities:
        return "No targets matched. Try relaxing --state/--category or collect more sources."

    rows = opportunities[:limit]
    header = (
        f"{'#':>3}  {'PRI':>5}  {'AGENCY':38} {'ST':2}  {'INCUMBENT':22} "
        f"{'EXPIRES':10}  {'PITCH BY':10}  {'ANNUAL':>8}  STAGE"
    )
    lines = [header, "-" * len(header)]
    for i, opp in enumerate(rows, 1):
        lines.append(
            f"{i:>3}  {opp.priority:>5.1f}  {opp.agency_name[:38]:38} "
            f"{opp.state or '--':2}  {opp.incumbent[:22]:22} "
            f"{_date(opp.earliest_end):10}  {_date(opp.budget_deadline):10}  "
            f"{_money(opp.annual_value):>8}  {STAGE_LABEL.get(opp.stage, opp.stage)}"
        )
    if len(opportunities) > limit:
        lines.append(f"... {len(opportunities) - limit} more (use --top to show more)")
    return "\n".join(lines)


def detail(opportunity: Opportunity) -> str:
    lines = [
        f"{opportunity.agency_name} ({opportunity.state})",
        f"  Incumbent    : {opportunity.incumbent}",
        f"  Systems      : {opportunity.category_labels or 'unclassified'}",
        f"  Annual value : {_money(opportunity.annual_value)}",
        f"  Expires      : {_date(opportunity.earliest_end)}",
        f"  Pitch window : {_date(opportunity.pitch_open)} -> {_date(opportunity.budget_deadline)}",
        f"  Stage        : {STAGE_LABEL.get(opportunity.stage, opportunity.stage)}",
        f"  Priority     : {opportunity.priority}",
        f"  Action       : {opportunity.action}",
    ]
    for reason in opportunity.rationale:
        lines.append(f"    - {reason}")
    for target in opportunity.targets:
        if target.source_url:
            lines.append(f"    source: {target.source} {target.source_url}")
    return "\n".join(lines)


# --- csv ------------------------------------------------------------------

CSV_COLUMNS = [
    "priority", "stage", "agency_name", "state", "incumbent", "systems",
    "annual_value", "expires", "pitch_open", "pitch_by_budget_deadline",
    "action", "sources", "rationale",
]


def to_csv(opportunities: List[Opportunity]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS)
    writer.writeheader()
    for opp in opportunities:
        writer.writerow(
            {
                "priority": opp.priority,
                "stage": opp.stage,
                "agency_name": opp.agency_name,
                "state": opp.state,
                "incumbent": opp.incumbent,
                "systems": opp.category_labels,
                "annual_value": f"{opp.annual_value:.0f}" if opp.annual_value else "",
                "expires": _date(opp.earliest_end),
                "pitch_open": _date(opp.pitch_open),
                "pitch_by_budget_deadline": _date(opp.budget_deadline),
                "action": opp.action,
                "sources": "; ".join(opp.sources),
                "rationale": " | ".join(opp.rationale),
            }
        )
    return buffer.getvalue()
