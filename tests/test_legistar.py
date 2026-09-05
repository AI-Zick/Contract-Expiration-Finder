"""Legistar council-agenda connector."""

import datetime as dt

from conftest import FakeFetcher

from pdcontracts.sources.legistar import (
    LegistarSource,
    extract_amount,
    extract_renewals,
    extract_term_months,
)

RESOLUTION = (
    "Resolution authorizing the Police Department to enter into a five-year "
    "agreement with Tyler Technologies, Inc. for a police records management "
    "system in an amount not to exceed $2,450,000, with two additional "
    "one-year renewal options"
)

MATTERS = [
    {"MatterId": 101, "MatterFile": "R-2025-114", "MatterBodyName": "Police Department",
     "MatterTitle": RESOLUTION, "MatterPassedDate": "2025-06-17T00:00:00"},
    {"MatterId": 102, "MatterFile": "R-2025-118", "MatterBodyName": "Committee on Public Safety",
     "MatterTitle": "Ordinance approving a 7 year contract with Motorola Solutions for "
                    "computer aided dispatch software, $1,200,000",
     "MatterPassedDate": "2025-08-05T00:00:00"},
    {"MatterId": 103, "MatterFile": "R-2025-120", "MatterBodyName": "Department of Streets",
     "MatterTitle": "Resolution authorizing repaving of Elm Street, $310,000",
     "MatterPassedDate": "2025-08-05T00:00:00"},
    {"MatterId": 104, "MatterFile": "R-2025-121", "MatterBodyName": "Fire Department",
     "MatterTitle": "Resolution for fire apparatus records management, $80,000",
     "MatterPassedDate": "2025-09-01T00:00:00"},
]


def source(rows=None):
    rows = MATTERS if rows is None else rows
    return LegistarSource(
        {"client": "example", "state": "IL", "jurisdiction": "Example City"},
        FakeFetcher(pages={"/matters": [rows, []]}),
    )


# --- text extraction ------------------------------------------------------

def test_extracts_a_spelled_out_term():
    assert extract_term_months("a five-year agreement") == 60


def test_extracts_a_numeric_term():
    assert extract_term_months("a 7 year contract") == 84


def test_extracts_a_parenthesized_term():
    assert extract_term_months("three (3) year term") == 36


def test_ignores_an_implausible_term():
    assert extract_term_months("a 99 year lease") is None


def test_takes_the_largest_dollar_figure():
    # Resolutions often cite an annual figure and a ceiling; the ceiling is the
    # contract value.
    assert extract_amount("$250,000 annually, not to exceed $1,250,000") == 1_250_000


def test_amount_absent_returns_none():
    assert extract_amount("no figure stated") is None


def test_extracts_renewal_options():
    assert extract_renewals("with two additional one-year renewal options") == 2


# --- collection -----------------------------------------------------------

def test_keeps_police_software_items():
    contracts = source().collect().contracts
    vendors = {c.vendor_canonical for c in contracts}
    assert vendors == {"Tyler Technologies", "Motorola Solutions"}


def test_drops_unrelated_and_non_police_items():
    descriptions = " ".join(c.description for c in source().collect().contracts)
    assert "repaving" not in descriptions
    assert "fire apparatus" not in descriptions


def test_derives_an_expiration_from_the_stated_term():
    """The whole point: a term in the resolution becomes a pitch window."""
    tyler = next(c for c in source().collect().contracts
                 if c.vendor_canonical == "Tyler Technologies")
    assert tyler.start_date == dt.date(2025, 6, 17)
    assert tyler.end_date == dt.date(2030, 6, 17)   # +60 months
    assert tyler.total_value == 2_450_000
    assert tyler.renewal_options == 2
    assert tyler.category == "rms"


def test_categorises_cad_separately_from_rms():
    cad = next(c for c in source().collect().contracts
               if c.vendor_canonical == "Motorola Solutions")
    assert cad.category == "cad"
    assert cad.end_date == dt.date(2032, 8, 5)      # +84 months


def test_links_back_to_the_council_item():
    contract = source().collect().contracts[0]
    assert "legistar.com" in contract.source_url
    assert contract.contract_number == "R-2025-114"


def test_confidence_is_below_a_contract_register():
    """Council items state a term, not an executed contract date."""
    assert source().collect().contracts[0].data_confidence < 0.75


def test_missing_client_is_reported():
    assert LegistarSource({}).collect().status == "error"


def test_unreachable_api_is_reported_not_raised():
    class Dead(FakeFetcher):
        def get_json(self, url, params=None, headers=None):
            from pdcontracts.sources.base import FetchError

            raise FetchError("timeout")

    result = LegistarSource({"client": "x"}, Dead()).collect()
    assert result.status == "error"
