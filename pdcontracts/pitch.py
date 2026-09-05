"""Turn contracts into ranked, dated sales recommendations.

The output answers two questions for every agency:

    WHEN  -- the window during which a pitch can still change the outcome,
             derived from the expiration date and the agency's budget calendar
    WHO   -- ordered by a priority score that trades off deal size, how
             winnable the segment is, agency size, and how urgent the timing is

Stages, relative to today:

    too_early         the window has not opened; note the date and wait
    pitch_now         inside the budget-influence window -- highest leverage
    procurement_live  money is likely allocated; compete on the RFP instead
    late              inside 3 months of expiry; incumbent probably renewed
    expired           past expiration; likely extended or auto-renewed
    unknown           no expiration date; work the next budget cycle
"""

from __future__ import annotations

import datetime as _dt
import math
from typing import List, Optional

from .fiscal import (
    add_months,
    budget_request_deadline,
    fiscal_year_label,
    influence_window_open,
    months_between,
    next_budget_cycle,
)
from .models import Agency, Contract, Target
from .taxonomy import CATEGORIES

# Months before expiration after which a first touch is probably too late to
# affect this cycle.
LATE_CUTOFF_MONTHS = 3

WEIGHTS = {
    "timing": 40.0,
    "value": 25.0,
    "winnability": 20.0,
    "reach": 10.0,
    "confidence": 5.0,
}


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _value_score(annual_value: Optional[float]) -> float:
    """Log-scaled deal size: $1k scores 0, $1M scores 1."""
    if not annual_value or annual_value <= 0:
        return 0.35  # unknown value -- assume mid so it is not buried
    return _clamp((math.log10(annual_value) - 3.0) / 3.0)


def _reach_score(sworn: Optional[int]) -> float:
    """Log-scaled agency size: 5 officers scores 0, 1000+ scores 1."""
    if not sworn or sworn <= 0:
        return 0.4
    return _clamp((math.log10(sworn) - 0.7) / 2.3)


def _winnability_score(category: str) -> float:
    """Inverse of how locked-in the incumbent is."""
    cat = CATEGORIES.get(category)
    if not cat:
        return 0.5
    return _clamp((6 - cat.stickiness) / 5.0)


def infer_end_date(contract: Contract) -> Optional[_dt.date]:
    """Estimate an expiration when the source did not provide one.

    Uses the category's typical term length from the start date. This is a
    guess and is flagged as such downstream via reduced confidence.
    """
    if contract.end_date:
        return contract.end_date
    if not contract.start_date:
        return None
    cat = CATEGORIES.get(contract.category)
    term = cat.typical_term_months if cat else 36
    return add_months(contract.start_date, term)


def build_target(
    contract: Contract,
    agency: Optional[Agency] = None,
    today: Optional[_dt.date] = None,
) -> Target:
    """Compute the pitch window, stage, and priority for one contract."""
    today = today or _dt.date.today()
    fiscal_start = agency.fiscal_start if agency else 7
    sworn = agency.sworn_officers if agency else None

    rationale: List[str] = []
    end_date = contract.end_date
    inferred = False
    if not end_date:
        end_date = infer_end_date(contract)
        inferred = end_date is not None
        if inferred:
            rationale.append(
                f"Expiration estimated from start date + typical "
                f"{CATEGORIES.get(contract.category).typical_term_months if CATEGORIES.get(contract.category) else 36}"
                f"-month term. Verify before acting."
            )

    cat = CATEGORIES.get(contract.category)
    lead_months = cat.lead_months if cat else 12
    annual = contract.effective_annual_value

    target = Target(
        agency_name=contract.agency_name,
        state=contract.state,
        vendor_canonical=contract.vendor_canonical or contract.vendor_raw,
        category=contract.category,
        end_date=end_date,
        annual_value=annual,
        description=contract.description,
        contract_number=contract.contract_number,
        contract_fingerprint=contract.fingerprint,
        source=contract.source,
        source_url=contract.source_url,
        data_confidence=contract.data_confidence,
    )

    if not end_date:
        # No expiration anywhere. The budget calendar is still actionable.
        deadline = next_budget_cycle(today, fiscal_start)
        target.stage = "unknown"
        target.budget_deadline = deadline
        target.pitch_open = add_months(deadline, -4)
        target.pitch_close = deadline
        target.action = (
            f"No expiration on record. File a public records request for the "
            f"contract term, and engage before the {deadline:%b %Y} budget request deadline."
        )
        rationale.append("No expiration date in any source for this contract.")
        target.rationale = rationale
        target.priority = round(
            WEIGHTS["value"] * _value_score(annual)
            + WEIGHTS["winnability"] * _winnability_score(contract.category)
            + WEIGHTS["reach"] * _reach_score(sworn)
            + WEIGHTS["timing"] * 0.25,
            1,
        )
        return target

    # Two independent constraints on when to start; respect the earlier one.
    budget_open = influence_window_open(end_date, fiscal_start)
    procurement_open = add_months(end_date, -lead_months)
    pitch_open = min(budget_open, procurement_open)
    deadline = budget_request_deadline(end_date, fiscal_start)
    late_cutoff = add_months(end_date, -LATE_CUTOFF_MONTHS)

    target.pitch_open = pitch_open
    target.pitch_close = deadline
    target.budget_deadline = deadline

    fy = fiscal_year_label(end_date, fiscal_start)
    rationale.append(
        f"Replacement must be funded in {fy} (fiscal year starts "
        f"{_dt.date(2000, fiscal_start, 1):%B}); department budget requests are "
        f"due around {deadline:%b %Y}."
    )
    if cat:
        rationale.append(
            f"{cat.label}: typical {cat.typical_term_months}-month term, "
            f"stickiness {cat.stickiness}/5, needs ~{cat.lead_months} months lead."
        )

    # --- stage ------------------------------------------------------------
    if today < pitch_open:
        stage = "too_early"
        months_out = months_between(today, pitch_open)
        timing = _clamp(1.0 - months_out / 18.0) * 0.7
        action = (
            f"Hold until {pitch_open:%b %Y}, then open the relationship ahead of "
            f"the {deadline:%b %Y} budget request."
        )
    elif today <= deadline:
        stage = "pitch_now"
        timing = 1.0
        action = (
            f"Pitch now. You have until roughly {deadline:%b %Y} to be written "
            f"into the {fy} budget request."
        )
    elif today <= late_cutoff:
        stage = "procurement_live"
        timing = 0.6
        action = (
            f"Budget request already filed. Compete on the solicitation \u2014 ask "
            f"procurement whether an RFP is planned before {end_date:%b %Y}."
        )
    elif today <= end_date:
        stage = "late"
        timing = 0.25
        action = (
            f"Expires {end_date:%b %Y}; incumbent has likely renewed. Position "
            f"for the following cycle and ask about extension terms."
        )
    else:
        stage = "expired"
        timing = 0.35
        action = (
            f"Contract expired {end_date:%b %Y} with no newer record found. "
            f"Likely extended or auto-renewed \u2014 confirm current status; an "
            f"agency operating on an extension is unusually reachable."
        )
        rationale.append("Past expiration with no successor contract in the data.")

    if inferred:
        timing *= 0.75
    if contract.renewal_options:
        rationale.append(
            f"{contract.renewal_options} renewal option(s) on the contract \u2014 the "
            f"buyer can extend without re-bidding, so treat the date as the "
            f"earliest decision point, not a guaranteed one."
        )
        timing *= 0.85
    if contract.auto_renew:
        rationale.append("Auto-renewing contract: find the notice-of-cancellation deadline, which precedes expiration.")

    confidence = _clamp(
        (contract.data_confidence + contract.classification_confidence) / 2.0
    )

    priority = (
        WEIGHTS["timing"] * timing
        + WEIGHTS["value"] * _value_score(annual)
        + WEIGHTS["winnability"] * _winnability_score(contract.category)
        + WEIGHTS["reach"] * _reach_score(sworn)
        + WEIGHTS["confidence"] * confidence
    )

    target.stage = stage
    target.action = action
    target.rationale = rationale
    target.priority = round(priority, 1)
    return target


def build_targets(
    contracts: List[Contract],
    agencies: Optional[dict] = None,
    today: Optional[_dt.date] = None,
) -> List[Target]:
    """Build and rank targets for many contracts."""
    agencies = agencies or {}
    targets = [
        build_target(c, agencies.get(c.agency_key), today)
        for c in contracts
    ]
    targets.sort(key=lambda t: t.priority, reverse=True)
    return targets
