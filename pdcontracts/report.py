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
import html
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
        # The earliest expiration is what forces the buying decision, so the
        # whole group inherits that member's timing.
        dated = [m for m in members if m.end_date]
        driver = min(dated, key=lambda m: m.end_date) if dated else members[0]

        values = [m.annual_value for m in members if m.annual_value]
        opp = Opportunity(
            agency_name=driver.agency_name,
            state=driver.state,
            incumbent=driver.vendor_canonical,
            categories=sorted({m.category for m in members if m.category}),
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
                f"({opp.category_labels}) -- likely one suite decision.",
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


# --- html -----------------------------------------------------------------

_HTML_HEAD = """<!doctype html>
<meta charset="utf-8">
<title>Police software contract pipeline</title>
<style>
  :root { color-scheme: light dark; --bg:#fbfbfa; --fg:#1c1c1a; --muted:#6b6b66;
          --line:#e3e3df; --card:#fff; --accent:#8a3324; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#16161a; --fg:#ececea; --muted:#9a9a95; --line:#2c2c31; --card:#1e1e23; }
  }
  body { margin:0; background:var(--bg); color:var(--fg);
         font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }
  .wrap { max-width:1180px; margin:0 auto; padding:32px 20px 64px; }
  h1 { font-size:24px; margin:0 0 4px; letter-spacing:-0.01em; }
  .sub { color:var(--muted); margin:0 0 24px; }
  .stats { display:flex; flex-wrap:wrap; gap:12px; margin-bottom:24px; }
  .stat { background:var(--card); border:1px solid var(--line); border-radius:8px;
          padding:12px 16px; min-width:120px; }
  .stat b { display:block; font-size:20px; }
  .stat span { color:var(--muted); font-size:12px; text-transform:uppercase;
               letter-spacing:.05em; }
  .scroll { overflow-x:auto; border:1px solid var(--line); border-radius:8px;
            background:var(--card); }
  table { border-collapse:collapse; width:100%; font-size:13px; }
  th,td { text-align:left; padding:9px 12px; border-bottom:1px solid var(--line);
          vertical-align:top; white-space:nowrap; }
  th { font-size:11px; text-transform:uppercase; letter-spacing:.05em;
       color:var(--muted); position:sticky; top:0; background:var(--card); }
  tr:last-child td { border-bottom:none; }
  td.wrap-cell { white-space:normal; min-width:280px; color:var(--muted); }
  .pri { font-variant-numeric:tabular-nums; font-weight:600; }
  .tag { display:inline-block; padding:2px 8px; border-radius:99px; font-size:11px;
         font-weight:600; }
  .s-pitch_now { background:#1f7a4d22; color:#1f7a4d; }
  .s-procurement_live { background:#b4690022; color:#b46900; }
  .s-too_early { background:#5a5a5a22; color:var(--muted); }
  .s-expired, .s-late { background:#8a332422; color:var(--accent); }
  .s-unknown { background:#5a5a5a22; color:var(--muted); }
  footer { color:var(--muted); font-size:12px; margin-top:28px; }
</style>
"""


def to_html(opportunities: List[Opportunity], generated: Optional[_dt.date] = None,
            note: str = "") -> str:
    generated = generated or _dt.date.today()
    by_stage: Dict[str, int] = defaultdict(int)
    for opp in opportunities:
        by_stage[opp.stage] += 1
    total_value = sum(o.annual_value or 0 for o in opportunities)

    parts = [_HTML_HEAD, '<div class="wrap">']
    parts.append("<h1>Police software contract pipeline</h1>")
    parts.append(
        f'<p class="sub">{len(opportunities)} opportunities &middot; generated '
        f'{generated:%d %b %Y}{" &middot; " + html.escape(note) if note else ""}</p>'
    )

    parts.append('<div class="stats">')
    parts.append(
        f'<div class="stat"><b>{by_stage.get("pitch_now", 0)}</b>'
        f'<span>Pitch now</span></div>'
    )
    parts.append(
        f'<div class="stat"><b>{by_stage.get("procurement_live", 0)}</b>'
        f'<span>Procurement live</span></div>'
    )
    parts.append(
        f'<div class="stat"><b>{by_stage.get("too_early", 0)}</b>'
        f'<span>Watchlist</span></div>'
    )
    parts.append(
        f'<div class="stat"><b>{_money(total_value)}</b>'
        f'<span>Annual value in view</span></div>'
    )
    parts.append("</div>")

    parts.append('<div class="scroll"><table><thead><tr>')
    for col in ["#", "Priority", "Stage", "Agency", "ST", "Incumbent", "Systems",
                "Annual", "Expires", "Pitch by", "Action"]:
        parts.append(f"<th>{col}</th>")
    parts.append("</tr></thead><tbody>")

    for i, opp in enumerate(opportunities, 1):
        parts.append("<tr>")
        parts.append(f"<td>{i}</td>")
        parts.append(f'<td class="pri">{opp.priority:.1f}</td>')
        parts.append(
            f'<td><span class="tag s-{html.escape(opp.stage)}">'
            f'{html.escape(STAGE_LABEL.get(opp.stage, opp.stage))}</span></td>'
        )
        parts.append(f"<td>{html.escape(opp.agency_name)}</td>")
        parts.append(f"<td>{html.escape(opp.state)}</td>")
        parts.append(f"<td>{html.escape(opp.incumbent)}</td>")
        parts.append(f"<td>{html.escape(opp.category_labels)}</td>")
        parts.append(f"<td>{_money(opp.annual_value)}</td>")
        parts.append(f"<td>{_date(opp.earliest_end)}</td>")
        parts.append(f"<td>{_date(opp.budget_deadline)}</td>")
        parts.append(f'<td class="wrap-cell">{html.escape(opp.action)}</td>')
        parts.append("</tr>")

    parts.append("</tbody></table></div>")
    parts.append(
        "<footer>Dates are derived from public procurement records and modeled "
        "budget calendars. Confirm expiration and renewal terms with the agency "
        "before acting.</footer>"
    )
    parts.append("</div>")
    return "\n".join(parts)
