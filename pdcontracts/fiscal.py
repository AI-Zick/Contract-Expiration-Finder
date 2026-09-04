"""Municipal budget-cycle math.

Government software is not bought when a contract expires. It is bought when
money for it is appropriated, which happens months earlier in a fixed annual
cycle. Getting this right is the difference between a well-timed pitch and one
that arrives after the money is already committed to the incumbent.

The cycle for a fiscal year starting on 1 July looks roughly like:

    Sep-Dec   finance issues budget instructions; departments build requests
    Jan-Feb   department budget requests are due to the city manager  <-- deadline
    Mar-May   manager's proposed budget, council hearings
    Jun       council adopts the budget
    Jul 1     fiscal year begins; funds available

To be in the FY2028 budget you have to have convinced the police department by
roughly January 2027 -- eighteen months before the money can be spent.
"""

from __future__ import annotations

import calendar
import datetime as _dt
from typing import Optional

# Months before the fiscal year starts that department budget requests are
# typically due to the finance office / city manager.
BUDGET_REQUEST_LEAD_MONTHS = 5
# How long before that deadline a vendor needs to have built the case with the
# department so the department is willing to put it in the request.
INFLUENCE_LEAD_MONTHS = 4


def add_months(date: _dt.date, months: int) -> _dt.date:
    """Shift a date by whole months, clamping the day to the target month."""
    total = date.month - 1 + months
    year = date.year + total // 12
    month = total % 12 + 1
    day = min(date.day, calendar.monthrange(year, month)[1])
    return _dt.date(year, month, day)


def months_between(start: _dt.date, end: _dt.date) -> float:
    """Approximate whole-and-fractional months between two dates."""
    return (end - start).days / 30.44


def fiscal_year_start_on_or_before(date: _dt.date, fiscal_start_month: int) -> _dt.date:
    """The start of the fiscal year that contains ``date``."""
    year = date.year if date.month >= fiscal_start_month else date.year - 1
    return _dt.date(year, fiscal_start_month, 1)


def fiscal_year_label(date: _dt.date, fiscal_start_month: int) -> str:
    """Fiscal year label, using the convention that FY is named for the year
    it ends in (the common US municipal convention for a July start)."""
    start = fiscal_year_start_on_or_before(date, fiscal_start_month)
    if fiscal_start_month == 1:
        return f"FY{start.year}"
    return f"FY{start.year + 1}"


def budget_request_deadline(expiration: _dt.date, fiscal_start_month: int) -> _dt.date:
    """When the department must have asked for the money.

    The replacement has to be funded in the fiscal year that contains the
    expiration date, so we work back from that fiscal year's start.
    """
    fy_start = fiscal_year_start_on_or_before(expiration, fiscal_start_month)
    return add_months(fy_start, -BUDGET_REQUEST_LEAD_MONTHS)


def influence_window_open(expiration: _dt.date, fiscal_start_month: int) -> _dt.date:
    """When to make first contact so the department can build you into its request."""
    return add_months(budget_request_deadline(expiration, fiscal_start_month), -INFLUENCE_LEAD_MONTHS)


def next_budget_cycle(today: _dt.date, fiscal_start_month: int) -> _dt.date:
    """The next budget-request deadline coming up, regardless of any contract.

    Useful for agencies where no expiration date is known -- you still want to
    reach them before their next budget request goes in.
    """
    fy_start = fiscal_year_start_on_or_before(today, fiscal_start_month)
    deadline = add_months(fy_start, -BUDGET_REQUEST_LEAD_MONTHS)
    while deadline < today:
        fy_start = add_months(fy_start, 12)
        deadline = add_months(fy_start, -BUDGET_REQUEST_LEAD_MONTHS)
    return deadline
