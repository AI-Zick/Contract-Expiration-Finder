from pdcontracts.classify import category_from_text, classify, match_vendor


def test_matches_vendor_through_corporate_suffixes():
    vendor, confidence = match_vendor("AXON ENTERPRISE, INC.")
    assert vendor.canonical == "Axon"
    assert confidence >= 0.9


def test_matches_acquired_brand_to_parent():
    assert match_vendor("Spillman Technologies")[0].canonical == "Motorola Solutions"
    assert match_vendor("New World Systems")[0].canonical == "Tyler Technologies"
    assert match_vendor("ShotSpotter Inc")[0].canonical == "SoundThinking"
    assert match_vendor("Zuercher Technologies")[0].canonical == "CentralSquare Technologies"


def test_matches_vendor_inside_longer_string():
    vendor, confidence = match_vendor("Motorola Solutions Credit Corporation")
    assert vendor.canonical == "Motorola Solutions"
    assert confidence < 0.95  # weaker evidence than an exact match


def test_unknown_vendor_returns_none():
    assert match_vendor("Bob's Landscaping")[0] is None
    assert match_vendor("")[0] is None


def test_description_disambiguates_multi_category_vendor():
    cad = classify("Motorola Solutions", "PremierOne computer aided dispatch software")
    bwc = classify("Motorola Solutions", "WatchGuard body worn camera program")
    assert cad.category == "cad"
    assert bwc.category == "bwc"


def test_hardware_purchase_from_software_vendor_is_not_software():
    result = classify("Axon Enterprise Inc", "Taser cartridges and ammunition")
    assert result.is_software is False


def test_radio_infrastructure_is_not_software():
    result = classify("Motorola Solutions", "P25 subscriber radio maintenance")
    assert result.category == "radio"
    assert result.is_software is False


def test_radio_software_licenses_still_count_as_software():
    result = classify("Motorola Solutions", "ASTRO 25 system software upgrade licenses")
    assert result.is_software is True


def test_unrelated_vendor_and_work_is_rejected():
    result = classify("ACME Paving LLC", "Parking lot repaving")
    assert result.is_software is False
    assert result.category == ""


def test_reseller_falls_back_to_description():
    result = classify("Carahsoft Technology Corp", "Real time crime center platform subscription")
    assert result.category == "rtcc"


def test_unknown_vendor_classified_from_description():
    result = classify("Regional Software Partners LLC", "Police records management system")
    assert result.category == "rms"
    assert result.is_software is True


def test_longer_keyword_phrase_wins():
    category, _ = category_from_text("mobile data terminal software for patrol")
    assert category == "dispatch_mobile"


def test_confidence_is_bounded():
    for vendor, desc in [
        ("Axon", "body worn camera"),
        ("", ""),
        ("Unknown Co", "widgets"),
    ]:
        result = classify(vendor, desc)
        assert 0.0 <= result.confidence <= 1.0


# --- precision: real strings from a live federal collection ---------------
# "Records management system" is generic enterprise IT. A live USAspending run
# surfaced all of these as police RMS leads before these vetoes existed.

import pytest

from pdcontracts.classify import category_veto


@pytest.mark.parametrize("description", [
    "INTERACTIVE PERSONNEL ELECTRONIC RECORDS MANAGEMENT SYSTEM SUPPORT SERVICES",
    "USDA, OFFICE OF INFORMATION AFFAIRS: ELECTRONIC RECORDS MANAGEMENT SYSTEM (ERMS)",
    "COLLABORATION & ELECTRONIC DOCUMENT RECORDS MANAGEMENT SYSTEM (EDRMS) SUPPORT",
    "ARMY FIRE AND EMERGENCY SERVICES RECORDS MANAGEMENT SYSTEM",
    "MULTIPLE PERSONNEL FUNCTIONS TO INCLUDE AUTOMATED RECORDS MANAGEMENT SYSTEM (ARMS)",
])
def test_non_police_records_systems_are_rejected(description):
    result = classify("", description)
    assert result.category == ""
    assert result.is_software is False
    assert category_veto(description)


@pytest.mark.parametrize("description", [
    "LAW ENFORCEMENT RECORDS MANAGEMENT SYSTEM PROCUREMENT - 1ST ORDER",
    "Police records management system and mobile field reporting",
    "Sheriff office records management system replacement",
    "JAG GRANT FOR RECORDS MANAGEMENT SYSTEM UPGRADE",
])
def test_police_records_systems_are_kept(description):
    result = classify("", description)
    assert result.category == "rms"
    assert result.is_software is True


def test_transit_cad_is_rejected():
    assert category_veto("HART WILL IMPLEMENT COMPUTER AIDED DISPATCH FOR PARATRANSIT")


def test_bare_cad_is_still_software():
    """CAD names a software product even with no other keyword in the text."""
    result = classify("", "COMPUTER AIDED DISPATCH (CAD)")
    assert result.category == "cad"
    assert result.is_software is True


def test_a_known_vendor_survives_a_generic_description():
    """Veto applies to text alone; a real public safety vendor overrides it."""
    result = classify("Tyler Technologies", "records management system")
    assert result.category == "rms"
