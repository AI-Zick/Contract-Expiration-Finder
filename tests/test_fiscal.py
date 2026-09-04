import datetime as dt

import pytest

from pdcontracts.fiscal import (
    add_months,
    budget_request_deadline,
    fiscal_year_label,
    fiscal_year_start_on_or_before,
    influence_window_open,
    next_budget_cycle,
)


def test_add_months_clamps_short_months():
    assert add_months(dt.date(2026, 1, 31), 1) == dt.date(2026, 2, 28)
    assert add_months(dt.date(2026, 3, 31), -1) == dt.date(2026, 2, 28)
    assert add_months(dt.date(2026, 6, 30), 12) == dt.date(2027, 6, 30)
    assert add_months(dt.date(2026, 6, 30), -24) == dt.date(2024, 6, 30)


def test_fiscal_year_containing_a_date():
    # July fiscal year: June 2028 falls in the year that began July 2027.
    assert fiscal_year_start_on_or_before(dt.date(2028, 6, 30), 7) == dt.date(2027, 7, 1)
    # ...and August 2028 falls in the next one.
    assert fiscal_year_start_on_or_before(dt.date(2028, 8, 1), 7) == dt.date(2028, 7, 1)


def test_fiscal_year_labels():
    assert fiscal_year_label(dt.date(2028, 6, 30), 7) == "FY2028"
    assert fiscal_year_label(dt.date(2028, 8, 1), 7) == "FY2029"
    # A calendar-year government names the year itself.
    assert fiscal_year_label(dt.date(2028, 8, 1), 1) == "FY2028"


def test_budget_deadline_precedes_expiration_by_more_than_a_year():
    expiration = dt.date(2028, 6, 30)
    deadline = budget_request_deadline(expiration, 7)
    assert deadline == dt.date(2027, 2, 1)
    assert (expiration - deadline).days > 365


def test_influence_window_opens_before_the_deadline():
    expiration = dt.date(2028, 6, 30)
    assert influence_window_open(expiration, 7) < budget_request_deadline(expiration, 7)


@pytest.mark.parametrize("fiscal_start", [1, 4, 7, 9, 10])
def test_deadline_is_always_before_expiration(fiscal_start):
    expiration = dt.date(2028, 6, 30)
    assert budget_request_deadline(expiration, fiscal_start) < expiration


def test_next_budget_cycle_is_in_the_future():
    today = dt.date(2026, 9, 4)
    for fiscal_start in (1, 4, 7, 9, 10):
        assert next_budget_cycle(today, fiscal_start) >= today
