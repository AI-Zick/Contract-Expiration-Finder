import datetime as dt

from pdcontracts.models import Agency, Contract
from pdcontracts.store import Store


def make(vendor="Tyler Technologies", end=dt.date(2028, 6, 30), **kwargs):
    return Contract(
        agency_name="Austin Police Department",
        state="TX",
        vendor_raw=vendor,
        vendor_canonical=vendor,
        end_date=end,
        category="rms",
        is_software=True,
        **kwargs,
    )


def test_same_contract_from_two_sources_collapses_to_one_row():
    store = Store(":memory:")
    store.upsert_contracts([make(source="portal-a"), make(source="portal-b")])
    assert store.count() == 1


def test_second_source_fills_gaps_without_erasing_known_values():
    store = Store(":memory:")
    store.upsert_contracts([make(total_value=5_000_000, source="a")])
    store.upsert_contracts([make(annual_value=714_285, source="b")])
    contract = store.contracts()[0]
    assert contract.total_value == 5_000_000  # not clobbered by the blank
    assert contract.annual_value == 714_285   # newly learned


def test_different_end_dates_are_different_contracts():
    store = Store(":memory:")
    store.upsert_contracts([make(end=dt.date(2028, 6, 30)), make(end=dt.date(2031, 6, 30))])
    assert store.count() == 2


def test_contract_number_identifies_a_contract_across_date_revisions():
    store = Store(":memory:")
    store.upsert_contracts([
        make(end=dt.date(2028, 6, 30), contract_number="PS-1"),
        make(end=dt.date(2029, 6, 30), contract_number="PS-1"),
    ])
    # Same paper, amended end date -- one contract, and the later data wins.
    assert store.count() == 1


def test_filters():
    store = Store(":memory:")
    store.upsert_contracts([
        make(source="a"),
        Contract(agency_name="X PD", state="OH", vendor_raw="Flock Safety",
                 vendor_canonical="Flock Safety", category="alpr", is_software=True,
                 end_date=dt.date(2027, 1, 1)),
        Contract(agency_name="Y PD", state="TX", vendor_raw="ACME",
                 category="", is_software=False, end_date=dt.date(2027, 1, 1)),
    ])
    assert len(store.contracts(states=["TX"])) == 1
    assert len(store.contracts(categories=["alpr"])) == 1
    assert len(store.contracts(software_only=True)) == 2
    assert len(store.contracts(software_only=False)) == 3
    assert len(store.contracts(vendor="Flock")) == 1


def test_agency_upsert_merges_and_infers_fiscal_year():
    store = Store(":memory:")
    store.upsert_agency(Agency(name="Austin Police Department", state="TX"))
    store.upsert_agency(Agency(name="Austin Police Department", state="TX",
                               sworn_officers=1800))
    agencies = store.get_agencies()
    assert len(agencies) == 1
    agency = list(agencies.values())[0]
    assert agency.sworn_officers == 1800
    assert agency.fiscal_start == 9  # Texas state default


def test_collection_log_records_failures():
    store = Store(":memory:")
    store.log_collection("socrata", "abcd-1234", 0, 0, "error", "404 not found")
    rows = store.collection_log()
    assert rows[0]["status"] == "error"
    assert "404" in rows[0]["message"]


def test_stats_summarize_coverage():
    store = Store(":memory:")
    store.upsert_contracts([make(source="a"), make(vendor="Mark43", source="b")])
    stats = store.stats()
    assert stats["total"] == 2
    assert stats["with_expiration"] == 2
    assert stats["by_state"]["TX"] == 2
