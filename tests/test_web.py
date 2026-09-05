"""Tests for the dashboard renderer and the local server."""

import datetime as dt
import json
import re
import threading
import urllib.request

import pytest

from pdcontracts.models import Target
from pdcontracts.report import group_opportunities
from pdcontracts.server import serve
from pdcontracts.web import (
    ASSET,
    build_payload,
    render_document,
    render_fragment,
)

TODAY = dt.date(2026, 9, 5)


def target(agency="Harborview Police Department", vendor="Tyler Technologies",
           category="rms", stage="pitch_now", **kw):
    base = dict(
        agency_name=agency, state="WA", vendor_canonical=vendor, category=category,
        end_date=dt.date(2028, 6, 30), annual_value=350_000, priority=67.4,
        stage=stage, pitch_open=dt.date(2026, 6, 30),
        budget_deadline=dt.date(2027, 2, 1), action="Pitch now.",
        description="New World RMS license", contract_number="WA-24-101",
        source="demo", rationale=["Because of the budget calendar."],
    )
    base.update(kw)
    return Target(**base)


def payload(targets=None, **kw):
    targets = targets or [target()]
    return build_payload(group_opportunities(targets), ["rms", "cad"], TODAY, **kw)


# --- payload --------------------------------------------------------------

def test_payload_carries_the_fields_the_page_needs():
    row = payload()["opportunities"][0]
    for key in ("agency", "state", "incumbent", "annual", "expires", "pitchOpen",
                "budgetDeadline", "stage", "priority", "action", "rationale",
                "categoryLabels", "contracts"):
        assert key in row, key


def test_payload_dates_are_iso_strings():
    row = payload()["opportunities"][0]
    assert row["expires"] == "2028-06-30"
    assert row["budgetDeadline"] == "2027-02-01"


def test_payload_includes_per_contract_detail_for_the_drawer():
    contract = payload()["opportunities"][0]["contracts"][0]
    assert contract["description"] == "New World RMS license"
    assert contract["number"] == "WA-24-101"
    assert contract["category"] == "Records Management System"


def test_focus_categories_are_labelled_for_display():
    assert payload()["focusLabels"] == [
        "Records Management System", "Computer-Aided Dispatch"
    ]


def test_missing_expiration_serializes_as_null_not_a_string():
    row = payload([target(end_date=None, stage="unknown")])["opportunities"][0]
    assert row["expires"] is None


def test_sample_flag_is_carried_through():
    data = payload(sample=True, sample_note="Fictional agencies.")
    assert data["sample"] is True
    assert data["sampleNote"] == "Fictional agencies."


# --- rendering ------------------------------------------------------------

def test_document_is_a_complete_standalone_page():
    page = render_document(payload())
    assert page.startswith("<!doctype html>")
    assert "<html" in page and "</html>" in page
    assert page.count("<body>") == 1


def test_fragment_has_no_document_shell():
    """The artifact host supplies its own <head>/<body>."""
    fragment = render_fragment(payload())
    assert "<!doctype" not in fragment.lower()
    assert "<body>" not in fragment.lower()
    assert "<title>Pitch Calendar</title>" in fragment


def test_placeholder_is_fully_replaced():
    assert "__PDCONTRACTS_DATA__" not in render_document(payload())


def test_embedded_json_parses_back():
    page = render_document(payload())
    blob = re.search(
        r'<script id="pdc-data" type="application/json">(.*?)</script>', page, re.S
    ).group(1)
    assert json.loads(blob)["opportunities"][0]["agency"] == "Harborview Police Department"


def test_agency_name_cannot_break_out_of_the_data_block():
    """A hostile agency name must not be able to close the script tag."""
    page = render_document(payload([target(agency='</script><script>alert(1)</script>')]))
    assert "</script><script>alert(1)" not in page
    blob = re.search(
        r'<script id="pdc-data" type="application/json">(.*?)</script>', page, re.S
    ).group(1)
    # Still valid JSON, and the payload survived intact.
    assert "alert(1)" in json.loads(blob)["opportunities"][0]["agency"]


def test_page_loads_no_blocked_external_assets():
    """Only fonts.googleapis.com is reachable under the artifact CSP."""
    page = render_document(payload())
    hosts = set(re.findall(r'https?://([^/"\s]+)', page))
    assert hosts <= {"fonts.googleapis.com", "fonts.gstatic.com"}, hosts


def test_asset_defines_both_theme_paths():
    css = ASSET.read_text()
    assert "prefers-color-scheme:dark" in css.replace(" ", "")
    assert '[data-theme="dark"]' in css
    assert '[data-theme="light"]' in css


def test_empty_pipeline_still_renders():
    page = render_document(build_payload([], ["rms"], TODAY))
    assert "<!doctype html>" in page
    assert '"opportunities": []' in page or '"opportunities":[]' in page


# --- server ---------------------------------------------------------------

@pytest.fixture
def live_server():
    calls = {"n": 0}

    def builder():
        calls["n"] += 1
        return group_opportunities([target()]), ["rms"], TODAY

    import socket
    from http.server import ThreadingHTTPServer

    from pdcontracts.server import make_handler

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(builder, quiet=True))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}", calls
    httpd.shutdown()
    httpd.server_close()


def get(url):
    with urllib.request.urlopen(url, timeout=5) as response:
        return response.status, response.read().decode("utf-8")


def test_server_serves_the_dashboard(live_server):
    base, _ = live_server
    status, body = get(base + "/")
    assert status == 200
    assert "Pitch Calendar" in body


def test_server_serves_json_and_csv(live_server):
    base, _ = live_server
    status, body = get(base + "/api/opportunities.json")
    assert status == 200
    assert json.loads(body)["opportunities"][0]["state"] == "WA"

    status, body = get(base + "/export.csv")
    assert status == 200
    assert body.startswith("priority,stage,agency_name")


def test_server_rebuilds_on_each_request(live_server):
    """A collection run in another terminal must show up on refresh."""
    base, calls = live_server
    get(base + "/")
    get(base + "/")
    assert calls["n"] >= 2


def test_server_returns_404_for_unknown_paths(live_server):
    base, _ = live_server
    with pytest.raises(urllib.error.HTTPError) as exc:
        get(base + "/nope")
    assert exc.value.code == 404
