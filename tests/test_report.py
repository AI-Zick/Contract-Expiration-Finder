import datetime as dt

from pdcontracts.models import Target
from pdcontracts.report import (
    as_opportunities,
    console_table,
    group_opportunities,
    to_csv,
)


def target(agency="Springfield Police Department", vendor="Tyler Technologies",
           category="rms", end=dt.date(2028, 6, 30), value=350_000, priority=60.0):
    return Target(
        agency_name=agency, state="IL", vendor_canonical=vendor, category=category,
        end_date=end, annual_value=value, priority=priority, stage="pitch_now",
        pitch_open=dt.date(2026, 6, 30), budget_deadline=dt.date(2027, 2, 1),
        action="Pitch now.", source="foia",
    )


def test_suite_contracts_collapse_into_one_opportunity():
    opportunities = group_opportunities([
        target(category="rms"), target(category="cad"), target(category="dispatch_mobile"),
    ])
    assert len(opportunities) == 1
    assert set(opportunities[0].categories) == {"rms", "cad", "dispatch_mobile"}


def test_grouped_annual_value_is_the_sum_of_its_contracts():
    opportunities = group_opportunities([
        target(category="rms", value=350_000), target(category="cad", value=275_000),
    ])
    assert opportunities[0].annual_value == 625_000


def test_grouping_is_timed_off_the_earliest_expiration():
    """The first system to expire is what forces the whole suite decision."""
    opportunities = group_opportunities([
        target(category="rms", end=dt.date(2030, 6, 30)),
        target(category="cad", end=dt.date(2028, 6, 30)),
    ])
    assert opportunities[0].earliest_end == dt.date(2028, 6, 30)


def test_different_vendors_at_one_agency_stay_separate():
    opportunities = group_opportunities([
        target(vendor="Tyler Technologies"), target(vendor="Mark43"),
    ])
    assert len(opportunities) == 2


def test_same_vendor_at_different_agencies_stays_separate():
    opportunities = group_opportunities([
        target(agency="Springfield Police Department"),
        target(agency="Lakeview Police Department"),
    ])
    assert len(opportunities) == 2


def test_breadth_raises_priority_but_does_not_multiply_it():
    one = group_opportunities([target(priority=60.0)])[0]
    three = group_opportunities([
        target(category="rms", priority=60.0),
        target(category="cad", priority=60.0),
        target(category="dispatch_mobile", priority=60.0),
    ])[0]
    assert one.priority < three.priority < one.priority * 2


def test_grouping_explains_itself_in_the_rationale():
    opportunity = group_opportunities([target(category="rms"), target(category="cad")])[0]
    assert any("suite decision" in r for r in opportunity.rationale)


def test_ungrouped_keeps_one_row_per_contract():
    assert len(as_opportunities([target(category="rms"), target(category="cad")])) == 2


def test_opportunities_are_sorted_by_priority():
    opportunities = group_opportunities([
        target(vendor="A", priority=10.0), target(vendor="B", priority=90.0),
    ])
    assert opportunities[0].priority > opportunities[1].priority


def test_csv_has_a_header_and_one_row_per_opportunity():
    csv_text = to_csv(group_opportunities([target(vendor="A"), target(vendor="B")]))
    lines = [line for line in csv_text.splitlines() if line.strip()]
    assert lines[0].startswith("priority,stage,agency_name")
    assert len(lines) == 3


def test_console_table_handles_an_empty_result():
    assert "No targets matched" in console_table([])


# --- amendment chains vs multiple systems ---------------------------------
# Denver's fifth, sixth and seventh amendatory agreements with Versaterm each
# appear as their own council item. They are one contract, not three.

def amendment(end, value, category="rms"):
    return target(agency="Denver Police Department", vendor="Versaterm",
                  category=category, end=end, value=value)


def test_amendment_chain_uses_the_current_agreement():
    """Timing off a superseded amendment points the rep at a contract that no
    longer exists."""
    opp = group_opportunities([
        amendment(dt.date(2024, 1, 4), 2_726_203),
        amendment(dt.date(2025, 11, 6), 4_854_124),
        amendment(dt.date(2028, 12, 22), 4_110_714),
    ])[0]
    assert opp.earliest_end == dt.date(2028, 12, 22)


def test_amendment_chain_does_not_sum_superseded_values():
    opp = group_opportunities([
        amendment(dt.date(2024, 1, 4), 2_726_203),
        amendment(dt.date(2028, 12, 22), 4_110_714),
    ])[0]
    assert opp.annual_value == 4_110_714


def test_amendment_chain_keeps_the_history_for_reference():
    opp = group_opportunities([
        amendment(dt.date(2024, 1, 4), 1),
        amendment(dt.date(2028, 12, 22), 2),
    ])[0]
    assert len(opp.targets) == 2


def test_different_systems_still_use_the_earliest_expiration():
    """The rule must not flip for genuinely separate systems."""
    opp = group_opportunities([
        amendment(dt.date(2030, 6, 30), 100_000, "rms"),
        amendment(dt.date(2027, 6, 30), 100_000, "cad"),
    ])[0]
    assert opp.earliest_end == dt.date(2027, 6, 30)


def test_mixed_case_takes_current_per_system_then_earliest():
    opp = group_opportunities([
        amendment(dt.date(2024, 1, 1), 10, "rms"),     # superseded
        amendment(dt.date(2030, 1, 1), 20, "rms"),     # current RMS
        amendment(dt.date(2027, 1, 1), 30, "cad"),     # current CAD
    ])[0]
    assert opp.earliest_end == dt.date(2027, 1, 1)
    assert opp.annual_value == 50                      # current RMS + current CAD
