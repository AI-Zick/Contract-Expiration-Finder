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


# --- query construction ---------------------------------------------------

def test_keyword_filter_is_pushed_to_the_server():
    """Downloading a city's whole legislative history to find two contracts is
    the difference between a fast source and an unusable one."""
    src = source()
    src.collect()
    params = [p for _, p in src.fetcher.calls if p]
    assert any("substringof" in (p.get("$filter") or "") for p in params)


def test_query_lowercases_both_sides():
    assert "tolower(MatterTitle)" in source()._keyword_filter()


def test_query_selects_only_needed_columns():
    src = source()
    src.collect()
    select = [p.get("$select") for _, p in src.fetcher.calls if p]
    assert any(s and "MatterTitle" in s and "MatterEXText" not in s for s in select)


def test_falls_back_when_the_server_rejects_the_filter():
    """Some Legistar deployments reject substringof; losing the whole city
    over that would be worse than a slower query."""
    from pdcontracts.sources.base import FetchError

    class PickyServer(FakeFetcher):
        def __init__(self):
            super().__init__()
            self.attempts = []

        def get_json(self, url, params=None, headers=None):
            where = (params or {}).get("$filter", "")
            self.attempts.append(where)
            if "substringof" in where:
                raise FetchError("400 Bad Request")
            return MATTERS if (params or {}).get("$skip", 0) == 0 else []

    src = LegistarSource({"client": "picky", "state": "IL"}, PickyServer())
    contracts = src.collect().contracts
    assert len(src.fetcher.attempts) >= 2          # tried filtered, then broad
    assert len(contracts) == 2                     # still got the data


def test_reports_error_when_both_queries_fail():
    from pdcontracts.sources.base import FetchError

    class Dead(FakeFetcher):
        def get_json(self, url, params=None, headers=None):
            raise FetchError("500")

    assert LegistarSource({"client": "x"}, Dead()).collect().status == "error"
