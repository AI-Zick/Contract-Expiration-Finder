import datetime as dt

from pdcontracts.models import Contract
from pdcontracts.pipeline import attach_agency_keys, run_source
from pdcontracts.store import Store

CSV_TEXT = """Department,Vendor,Description,Start,Term Thru,Amount
Springfield Police Department,Tyler Technologies,Records management system,07/01/2021,06/30/2028,2450000
Springfield Police Department,ACME Paving,Resurfacing of impound lot,05/01/2025,10/31/2025,310000
"""


def write(tmp_path, text=CSV_TEXT):
    path = tmp_path / "contracts.csv"
    path.write_text(text)
    return str(path)


def test_run_source_stores_software_and_drops_the_rest(tmp_path):
    store = Store(":memory:")
    result = run_source(
        {"type": "csv", "path": write(tmp_path), "state": "IL"},
        store,
        {"min_classification_confidence": 0.3},
    )
    assert result.status == "ok"
    assert store.count() == 1
    assert store.contracts()[0].vendor_canonical == "Tyler Technologies"


def test_run_source_logs_every_run(tmp_path):
    store = Store(":memory:")
    run_source({"type": "csv", "path": write(tmp_path), "state": "IL"}, store, {})
    assert store.collection_log()[0]["status"] == "ok"


def test_unknown_source_type_is_logged_not_raised():
    store = Store(":memory:")
    result = run_source({"type": "nonexistent"}, store, {})
    assert result.status == "error"
    assert store.collection_log()[0]["status"] == "error"


def test_missing_file_is_reported_not_raised():
    store = Store(":memory:")
    result = run_source({"type": "csv", "path": "/nope/missing.csv"}, store, {})
    assert result.status == "error"


def test_agency_name_variants_resolve_to_one_agency():
    store = Store(":memory:")
    contracts = [
        Contract(agency_name="Austin Police Department", state="TX", vendor_raw="A"),
        Contract(agency_name="Austin Police Dept", state="TX", vendor_raw="B"),
        Contract(agency_name="City of Austin Police Department", state="TX", vendor_raw="C"),
    ]
    attach_agency_keys(contracts, store)
    assert len({c.agency_key for c in contracts}) == 1


def test_same_agency_name_in_two_states_stays_separate():
    store = Store(":memory:")
    contracts = [
        Contract(agency_name="Springfield Police Department", state="IL", vendor_raw="A"),
        Contract(agency_name="Springfield Police Department", state="MO", vendor_raw="B"),
    ]
    attach_agency_keys(contracts, store)
    assert len({c.agency_key for c in contracts}) == 2
