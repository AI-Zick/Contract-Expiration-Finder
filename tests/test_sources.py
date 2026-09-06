import datetime as dt

import pytest

from conftest import FakeFetcher

from pdcontracts.sources.csvfile import CSVSource
from pdcontracts.sources.socrata import SocrataSource
from pdcontracts.sources.usaspending import USASpendingSource

SOCRATA_ROWS = [
    {
        "vendor_name": "AXON ENTERPRISE INC",
        "department": "POLICE",
        "short_description": "Body worn camera and evidence storage",
        "start_date": "2024-01-01T00:00:00.000",
        "end_date": "2028-12-31T00:00:00.000",
        "contract_amount": "1750000",
        "purchase_order_number": "PO-100",
    },
    {
        "vendor_name": "TYLER TECHNOLOGIES INC",
        "department": "POLICE",
        "short_description": "Records management system license and support",
        "start_date": "2021-07-01T00:00:00.000",
        "end_date": "2028-06-30T00:00:00.000",
        "contract_amount": "2450000",
        "purchase_order_number": "PO-101",
    },
    {
        "vendor_name": "GREEN THUMB LANDSCAPING",
        "department": "PARKS AND RECREATION",
        "short_description": "Mowing services",
        "start_date": "2025-01-01T00:00:00.000",
        "end_date": "2026-12-31T00:00:00.000",
        "contract_amount": "90000",
        "purchase_order_number": "PO-102",
    },
]


def socrata_source(rows):
    # sample page, then one full page, then an empty page to end paging
    fetcher = FakeFetcher(pages={"/resource/": [rows, rows, []]})
    return SocrataSource(
        {"domain": "data.example.gov", "dataset": "abcd-1234",
         "state": "IL", "jurisdiction": "Example City"},
        fetcher,
    )


def test_socrata_infers_columns_and_keeps_only_police_rows():
    result = socrata_source(SOCRATA_ROWS).collect()
    assert result.status == "ok"
    assert len(result.contracts) == 2
    vendors = {c.vendor_canonical for c in result.contracts}
    assert vendors == {"Axon", "Tyler Technologies"}


def test_socrata_parses_dates_amounts_and_provenance():
    contracts = socrata_source(SOCRATA_ROWS).collect().contracts
    tyler = next(c for c in contracts if c.vendor_canonical == "Tyler Technologies")
    assert tyler.end_date == dt.date(2028, 6, 30)
    assert tyler.total_value == 2_450_000
    assert tyler.category == "rms"
    assert tyler.state == "IL"
    assert tyler.source == "socrata"
    assert "abcd-1234" in tyler.source_url
    assert tyler.contract_number == "PO-101"


def test_socrata_qualifies_a_bare_department_name_with_its_city():
    contracts = socrata_source(SOCRATA_ROWS).collect().contracts
    assert all("Example City" in c.agency_name for c in contracts)


def test_socrata_filters_police_rows_server_side_when_it_can():
    source = socrata_source(SOCRATA_ROWS)
    source.collect()
    wheres = [p.get("$where") for _, p in source.fetcher.calls if p]
    assert any(w and "POLICE" in w for w in wheres)


def test_socrata_reports_error_instead_of_raising_on_a_dead_portal():
    class Boom(FakeFetcher):
        def get_json(self, url, params=None, headers=None):
            from pdcontracts.sources.base import FetchError

            raise FetchError("503 service unavailable")

    source = SocrataSource({"domain": "d", "dataset": "x"}, Boom())
    result = source.collect()
    assert result.status == "error"
    assert "503" in result.message


def test_socrata_reports_error_when_no_vendor_column_exists():
    fetcher = FakeFetcher(pages={"/resource/": [[{"alpha": "1", "beta": "2"}]]})
    result = SocrataSource({"domain": "d", "dataset": "x"}, fetcher).collect()
    assert result.status == "error"
    assert "vendor" in result.message


def test_socrata_discovery_lists_datasets():
    fetcher = FakeFetcher(responses={"catalog": {
        "results": [{"resource": {"id": "ab12-cd34", "name": "Contracts",
                                  "description": "All city contracts",
                                  "updatedAt": "2026-01-01T00:00:00.000Z",
                                  "columns_field_name": ["vendor", "end_date"]}}]
    }})
    found = SocrataSource({"domain": "data.example.gov"}, fetcher).discover()
    assert found[0]["dataset"] == "ab12-cd34"


USASPENDING_PAGE = {
    "results": [
        {
            "Award ID": "GS-1234",
            "Recipient Name": "MARK43 INC",
            "Start Date": "2025-01-01",
            "End Date": "2029-12-31",
            "Award Amount": 4_500_000,
            "Description": "RECORDS MANAGEMENT SYSTEM SOFTWARE",
            "Awarding Sub Agency": "Federal Bureau of Investigation",
            "Place of Performance State Code": "VA",
            "generated_internal_id": "CONT_AWD_1",
        }
    ],
    "page_metadata": {"hasNext": False},
}


def test_usaspending_parses_a_contract_award():
    source = USASpendingSource(
        {"keywords": ["records management system"], "include_grants": False},
        FakeFetcher(responses={"spending_by_award": USASPENDING_PAGE}),
    )
    result = source.collect()
    assert result.status == "ok"
    contract = result.contracts[0]
    assert contract.vendor_canonical == "Mark43"
    assert contract.end_date == dt.date(2029, 12, 31)
    assert contract.agency_name == "Federal Bureau of Investigation"
    assert "CONT_AWD_1" in contract.source_url


def test_usaspending_treats_a_grant_as_an_unawarded_signal():
    grant_page = {
        "results": [{
            "Award ID": "2025-DJ-BX-0001",
            "Recipient Name": "CITY OF SPRINGFIELD",
            "Start Date": "2026-01-01",
            "End Date": "2028-12-31",
            "Award Amount": 750_000,
            "Description": "JAG GRANT FOR RECORDS MANAGEMENT SYSTEM UPGRADE",
            "Awarding Sub Agency": "Bureau of Justice Assistance",
            "Place of Performance State Code": "IL",
            "generated_internal_id": "ASST_1",
        }],
        "page_metadata": {"hasNext": False},
    }
    source = USASpendingSource(
        {"keywords": ["records management system"]},
        FakeFetcher(responses={"spending_by_award": grant_page}),
    )
    contracts = source.collect().contracts
    grant = next(c for c in contracts if "UNAWARDED" in c.vendor_raw)
    # The city is the buyer, and no vendor has been chosen yet -- that is the
    # whole point of tracking grants.
    assert grant.agency_name == "CITY OF SPRINGFIELD"
    assert grant.category == "rms"


def test_usaspending_survives_a_failing_keyword():
    class Flaky(FakeFetcher):
        def post_json(self, url, payload, headers=None):
            from pdcontracts.sources.base import FetchError

            raise FetchError("timeout")

    source = USASpendingSource({"keywords": ["x"]}, Flaky())
    result = source.collect()
    assert result.status == "error"
    assert "timeout" in result.message


CSV_TEXT = """Department,Vendor Name,Description of Services,Contract Start,Term Thru,Not To Exceed Amount,Contract No
Springfield Police Department,Tyler Technologies Inc,New World records management system,07/01/2021,06/30/2028,"$2,450,000",PS-14
Springfield Police Department,ACME Paving LLC,Resurfacing of impound lot,05/01/2025,10/31/2025,"$310,000",PW-88
"""


def test_csv_import_maps_a_human_spreadsheet():
    result = CSVSource({"state": "IL", "source_name": "foia"}).collect(text=CSV_TEXT)
    assert result.status == "ok"
    tyler = next(c for c in result.contracts if c.vendor_canonical == "Tyler Technologies")
    assert tyler.end_date == dt.date(2028, 6, 30)
    assert tyler.total_value == 2_450_000
    assert tyler.category == "rms"
    assert tyler.state == "IL"


def test_csv_import_keeps_non_software_rows_for_the_pipeline_to_drop():
    # The source does not decide relevance; it records what it saw and lets the
    # pipeline apply the software filter, so nothing is silently discarded.
    result = CSVSource({"state": "IL"}).collect(text=CSV_TEXT)
    paving = next(c for c in result.contracts if "ACME" in c.vendor_raw)
    assert paving.is_software is False


def test_csv_import_reports_a_missing_vendor_column():
    result = CSVSource({}).collect(text="alpha,beta\n1,2\n")
    assert result.status == "error"
    assert "vendor" in result.message


def test_csv_import_handles_an_empty_file():
    assert CSVSource({}).collect(text="").status == "empty"


# --- federal grants: buyer must actually be law enforcement ---------------

def _grant(recipient, description, awarder="Bureau of Justice Assistance"):
    return {
        "results": [{
            "Award ID": "X-1", "Recipient Name": recipient,
            "Start Date": "2025-01-01", "End Date": "2029-12-31",
            "Award Amount": 5_000_000, "Description": description,
            "Awarding Sub Agency": awarder,
            "Place of Performance State Code": "CA",
            "generated_internal_id": "ASST_1",
        }],
        "page_metadata": {"hasNext": False},
    }


def _collect_grant(recipient, description, awarder="Bureau of Justice Assistance"):
    source = USASpendingSource(
        {"keywords": ["computer aided dispatch"]},
        FakeFetcher(responses={"spending_by_award": _grant(recipient, description, awarder)}),
    )
    return source.collect().contracts


def test_transit_cad_grant_is_not_a_police_lead():
    """Transit agencies run computer-aided dispatch too. A live run surfaced
    three of them as police-software leads."""
    assert _collect_grant("GOLDEN EMPIRE TRANSIT DISTRICT",
                          "COMPUTER AIDED DISPATCH AND AVL REPLACEMENT",
                          "Federal Transit Administration") == []


def test_transit_authority_excluded_even_from_a_justice_grant():
    """The buyer name decides; the funding programme cannot override it."""
    assert _collect_grant("HILLSBOROUGH TRANSIT AUTHORITY", "CAD SYSTEM UPGRADE",
                          "Bureau of Justice Assistance") == []


def test_transit_police_department_stays_in_scope():
    assert len(_collect_grant("BAY AREA RAPID TRANSIT POLICE DEPARTMENT",
                              "CAD SYSTEM UPGRADE")) == 1


def test_city_grant_naming_police_is_kept():
    contracts = _collect_grant("CITY OF CONCORD",
                               "POLICE RECORDS MANAGEMENT SYSTEM UPGRADE")
    assert len(contracts) == 1
    assert contracts[0].agency_name == "CITY OF CONCORD"


def test_sheriff_grant_is_kept():
    assert len(_collect_grant("COUNTY OF X",
                              "SHERIFF COMPUTER AIDED DISPATCH REPLACEMENT")) == 1


# --- retry timing ---------------------------------------------------------

def test_no_backoff_sleep_after_the_final_attempt(monkeypatch):
    """A sweep of hundreds of probes is dominated by dead time otherwise."""
    import pdcontracts.sources.base as base

    slept = []
    monkeypatch.setattr(base.time, "sleep", lambda s: slept.append(s))

    class Boom:
        def get(self, *a, **k):
            raise OSError("refused")

    fetcher = base.HttpFetcher(retries=1, delay=0)
    fetcher._session = Boom()
    with pytest.raises(base.FetchError):
        fetcher.get_text("https://example.invalid/")
    assert slept == []


def test_backoff_still_happens_between_real_retries(monkeypatch):
    import pdcontracts.sources.base as base

    slept = []
    monkeypatch.setattr(base.time, "sleep", lambda s: slept.append(s))

    class Boom:
        def get(self, *a, **k):
            raise OSError("refused")

    fetcher = base.HttpFetcher(retries=3, delay=0)
    fetcher._session = Boom()
    with pytest.raises(base.FetchError):
        fetcher.get_text("https://example.invalid/")
    assert len(slept) == 2          # between attempts, not after the last


# --- per-source time budget -----------------------------------------------
# One jurisdiction whose API hangs must not stall a national run behind it.

def test_source_reports_when_it_is_over_budget():
    from pdcontracts.sources.base import Source

    source = Source({"budget_seconds": 0})
    assert not source.over_budget()      # clock not started yet
    source.start_clock()
    assert source.over_budget()


def test_budget_defaults_to_something_finite():
    from pdcontracts.sources.base import DEFAULT_BUDGET_SECONDS, Source

    assert 0 < DEFAULT_BUDGET_SECONDS <= 600
    assert Source({}).budget_seconds == DEFAULT_BUDGET_SECONDS


def test_legistar_truncates_at_its_budget_and_says_so():
    from pdcontracts.sources.legistar import LegistarSource

    class Endless(FakeFetcher):
        def __init__(self):
            super().__init__()
            self.pages_served = 0

        def get_json(self, url, params=None, headers=None):
            self.pages_served += 1
            return [{"MatterId": 1, "MatterTitle": "x", "MatterBodyName": "y"}] * 1000

    source = LegistarSource({"client": "slow", "budget_seconds": 0}, Endless())
    result = source.collect()
    assert source.fetcher.pages_served == 0     # stopped before the first page
    assert "budget" in source.query_mode


def test_usaspending_stops_paging_at_its_budget():
    class Endless(FakeFetcher):
        def __init__(self):
            super().__init__()
            self.calls_made = 0

        def post_json(self, url, payload, headers=None):
            self.calls_made += 1
            return {"results": [], "page_metadata": {"hasNext": True}}

    source = USASpendingSource(
        {"keywords": ["x"], "max_pages": 50, "budget_seconds": 0}, Endless()
    )
    source.collect()
    assert source.fetcher.calls_made == 0
