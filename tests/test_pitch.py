import datetime as dt

import pytest

from pdcontracts.models import Agency, Contract
from pdcontracts.pitch import build_target, build_targets, infer_end_date

TODAY = dt.date(2026, 9, 4)
AUSTIN = Agency(name="Austin Police Department", state="TX", sworn_officers=1800,
                fiscal_year_start_month=10)
GENERIC = Agency(name="Anytown Police Department", state="OH", sworn_officers=50)


def make(category="rms", end=None, value=500_000, **kwargs):
    return Contract(
        agency_name="Anytown Police Department",
        state="OH",
        vendor_raw="Tyler Technologies",
        vendor_canonical="Tyler Technologies",
        category=category,
        end_date=end,
        annual_value=value,
        data_confidence=0.8,
        classification_confidence=0.9,
        **kwargs,
    )


def test_stage_is_pitch_now_inside_the_budget_window():
    target = build_target(make(end=dt.date(2028, 6, 30)), GENERIC, TODAY)
    assert target.stage == "pitch_now"
    assert target.pitch_open <= TODAY <= target.budget_deadline


def test_stage_is_too_early_for_a_distant_expiration():
    target = build_target(make(end=dt.date(2033, 6, 30)), GENERIC, TODAY)
    assert target.stage == "too_early"
    assert target.pitch_open > TODAY


def test_stage_is_expired_after_the_end_date():
    target = build_target(make(end=dt.date(2025, 6, 30)), GENERIC, TODAY)
    assert target.stage == "expired"


def test_stage_is_late_just_before_expiration():
    target = build_target(make(end=dt.date(2026, 10, 15)), GENERIC, TODAY)
    assert target.stage == "late"


def test_stage_is_procurement_live_after_the_budget_deadline():
    target = build_target(make(end=dt.date(2027, 3, 31)), GENERIC, TODAY)
    assert target.stage == "procurement_live"


def test_missing_expiration_falls_back_to_the_budget_calendar():
    target = build_target(make(end=None), GENERIC, TODAY)
    assert target.stage == "unknown"
    assert target.budget_deadline is not None
    assert "records request" in target.action.lower()


def test_end_date_inferred_from_start_and_category_term():
    contract = make(end=None)
    contract.start_date = dt.date(2022, 7, 1)
    # RMS carries an 84-month typical term.
    assert infer_end_date(contract) == dt.date(2029, 7, 1)


def test_inferred_expiration_is_flagged_in_the_rationale():
    contract = make(end=None)
    contract.start_date = dt.date(2022, 7, 1)
    target = build_target(contract, GENERIC, TODAY)
    assert any("estimated" in r.lower() for r in target.rationale)


def test_agency_fiscal_calendar_changes_the_deadline():
    contract = make(end=dt.date(2028, 6, 30))
    july = build_target(contract, GENERIC, TODAY)
    october = build_target(contract, AUSTIN, TODAY)
    assert july.budget_deadline != october.budget_deadline


def test_bigger_contract_outranks_smaller_all_else_equal():
    big = build_target(make(end=dt.date(2028, 6, 30), value=2_000_000), GENERIC, TODAY)
    small = build_target(make(end=dt.date(2028, 6, 30), value=20_000), GENERIC, TODAY)
    assert big.priority > small.priority


def test_larger_agency_outranks_smaller_all_else_equal():
    contract = make(end=dt.date(2028, 6, 30))
    big_agency = Agency(name="Big PD", state="OH", sworn_officers=3000)
    small_agency = Agency(name="Small PD", state="OH", sworn_officers=8)
    assert build_target(contract, big_agency, TODAY).priority > build_target(
        contract, small_agency, TODAY
    ).priority


def test_less_sticky_category_scores_higher_at_equal_timing():
    # Categories carry different lead times, so they only share a stage for
    # some expirations. 2027-07-01 puts both in pitch_now, isolating
    # stickiness as the only difference: ALPR churns, CAD effectively does not.
    end = dt.date(2027, 7, 1)
    alpr = build_target(make(category="alpr", end=end), GENERIC, TODAY)
    cad = build_target(make(category="cad", end=end), GENERIC, TODAY)
    assert alpr.stage == cad.stage == "pitch_now"
    assert alpr.priority > cad.priority


def test_timing_outweighs_winnability():
    """A timely locked-in deal beats a churn-prone one that is not yet live.

    This is deliberate: a rep's next call should go to the agency whose money
    is being decided now, even if that segment is harder to displace.
    """
    cad_now = build_target(make(category="cad", end=dt.date(2028, 6, 30)), GENERIC, TODAY)
    alpr_early = build_target(make(category="alpr", end=dt.date(2028, 6, 30)), GENERIC, TODAY)
    assert cad_now.stage == "pitch_now"
    assert alpr_early.stage == "too_early"
    assert cad_now.priority > alpr_early.priority


def test_renewal_options_reduce_urgency():
    plain = build_target(make(end=dt.date(2028, 6, 30)), GENERIC, TODAY)
    with_options = build_target(
        make(end=dt.date(2028, 6, 30), renewal_options=2), GENERIC, TODAY
    )
    assert with_options.priority < plain.priority
    assert any("renewal option" in r for r in with_options.rationale)


def test_auto_renew_warns_about_the_notice_deadline():
    target = build_target(make(end=dt.date(2028, 6, 30), auto_renew=True), GENERIC, TODAY)
    assert any("notice" in r.lower() for r in target.rationale)


def test_pitch_window_always_precedes_expiration():
    for end in [dt.date(2027, 1, 1), dt.date(2028, 6, 30), dt.date(2031, 12, 31)]:
        target = build_target(make(end=end), GENERIC, TODAY)
        assert target.pitch_open < end
        assert target.budget_deadline < end


def test_targets_are_returned_in_priority_order():
    contracts = [
        make(end=dt.date(2028, 6, 30), value=10_000),
        make(end=dt.date(2028, 6, 30), value=3_000_000),
        make(end=dt.date(2033, 6, 30), value=500_000),
    ]
    targets = build_targets(contracts, {}, TODAY)
    assert targets == sorted(targets, key=lambda t: t.priority, reverse=True)


@pytest.mark.parametrize("category", ["rms", "cad", "dispatch_mobile"])
def test_focus_categories_get_long_lead_times(category):
    """RMS/CAD/MDT must open the window well over a year out."""
    target = build_target(make(category=category, end=dt.date(2030, 6, 30)), GENERIC, TODAY)
    months_of_lead = (dt.date(2030, 6, 30) - target.pitch_open).days / 30.44
    assert months_of_lead >= 12
