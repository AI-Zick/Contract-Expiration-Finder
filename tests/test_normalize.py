import datetime as dt

import pytest

from pdcontracts.normalize import (
    clean_text,
    looks_like_law_enforcement,
    normalize_agency_name,
    normalize_state,
    normalize_vendor_name,
    parse_bool,
    parse_date,
    parse_money,
)


@pytest.mark.parametrize(
    "value,expected",
    [
        ("2027-06-30", dt.date(2027, 6, 30)),
        ("06/30/2027", dt.date(2027, 6, 30)),
        ("6/30/27", dt.date(2027, 6, 30)),
        ("2027-06-30T00:00:00.000", dt.date(2027, 6, 30)),
        ("June 30, 2027", dt.date(2027, 6, 30)),
        ("30-Jun-2027", dt.date(2027, 6, 30)),
        ("20270630", dt.date(2027, 6, 30)),
        (dt.date(2027, 6, 30), dt.date(2027, 6, 30)),
        (dt.datetime(2027, 6, 30, 12), dt.date(2027, 6, 30)),
    ],
)
def test_parse_date_formats(value, expected):
    assert parse_date(value) == expected


@pytest.mark.parametrize("value", ["", None, "N/A", "TBD", "ongoing", "not a date"])
def test_parse_date_rejects_junk(value):
    assert parse_date(value) is None


def test_bare_year_becomes_year_end():
    # An expiration given as just a year should not be read as January 1,
    # which would make the contract look eleven months more urgent.
    assert parse_date("2027") == dt.date(2027, 12, 31)


@pytest.mark.parametrize(
    "value,expected",
    [
        ("$1,234,567.89", 1234567.89),
        ("1234567.89", 1234567.89),
        (1234, 1234.0),
        ("(500)", -500.0),
        ("$0", 0.0),
    ],
)
def test_parse_money(value, expected):
    assert parse_money(value) == expected


@pytest.mark.parametrize("value", ["", None, "N/A", "see attached"])
def test_parse_money_rejects_junk(value):
    assert parse_money(value) is None


def test_vendor_normalization_collapses_corporate_noise():
    variants = [
        "Axon Enterprise, Inc.",
        "AXON ENTERPRISE INC",
        "Axon Enterprise Incorporated",
        "axon enterprise",
    ]
    normalized = {normalize_vendor_name(v) for v in variants}
    assert len(normalized) == 1


def test_agency_normalization_matches_abbreviations():
    assert normalize_agency_name("Austin Police Dept") == normalize_agency_name(
        "Austin Police Department"
    )
    assert normalize_agency_name("City of Austin Police Department") == (
        normalize_agency_name("Austin Police Department")
    )


def test_state_normalization():
    assert normalize_state("California") == "CA"
    assert normalize_state("ca") == "CA"
    assert normalize_state("Republic of Texas") == ""
    assert normalize_state(None) == ""


@pytest.mark.parametrize(
    "text",
    [
        "Chicago Police Department",
        "Riverside County Sheriff's Office",
        "Department of Public Safety",
        "State Highway Patrol",
        "Police & Fire Communications",
    ],
)
def test_detects_law_enforcement(text):
    assert looks_like_law_enforcement(text)


@pytest.mark.parametrize(
    "text",
    [
        "Fire Department",
        "Parks and Recreation",
        "Animal Control",
        "Department of Public Works",
        "",
    ],
)
def test_rejects_non_law_enforcement(text):
    assert not looks_like_law_enforcement(text)


def test_parse_bool():
    assert parse_bool("Yes") is True
    assert parse_bool("N") is False
    assert parse_bool("maybe") is None


def test_clean_text_truncates_and_collapses():
    assert clean_text("  a\n\n  b  ") == "a b"
    assert len(clean_text("x" * 5000, limit=100)) == 100
