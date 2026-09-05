"""End-to-end CLI tests against a temporary database."""

import datetime as dt
from pathlib import Path

import pytest

from pdcontracts.cli import main

ROOT = Path(__file__).resolve().parent.parent
SETTINGS = str(ROOT / "config" / "settings.yml")
SOURCES = str(ROOT / "config" / "sources.yml")
SAMPLE = str(ROOT / "samples" / "sample_foia_response.csv")


@pytest.fixture
def db(tmp_path):
    return str(tmp_path / "test.sqlite")


def run(db, *args):
    return main(["--db", db, "--settings", SETTINGS, "--sources", SOURCES, *args])


def test_init_creates_a_database_and_loads_agencies(db, capsys):
    assert run(db, "init", "--agencies", str(ROOT / "config" / "agencies_seed.csv")) == 0
    assert "agencies" in capsys.readouterr().out
    assert Path(db).exists()


def test_full_workflow_import_then_target(db, capsys):
    run(db, "init")
    capsys.readouterr()

    assert run(db, "import", SAMPLE, "--state", "IL") == 0
    assert "imported" in capsys.readouterr().out

    assert run(db, "targets", "--today", "2026-09-04") == 0
    out = capsys.readouterr().out
    # RMS/CAD/MDT focus: Tyler and CentralSquare are in, Flock and Axon are not.
    assert "Tyler Technologies" in out
    assert "CentralSquare" in out
    assert "Flock" not in out
    assert "Axon" not in out


def test_all_categories_flag_widens_the_view(db, capsys):
    run(db, "init")
    run(db, "import", SAMPLE, "--state", "IL")
    capsys.readouterr()
    run(db, "targets", "--today", "2026-09-04", "--all-categories")
    out = capsys.readouterr().out
    assert "Flock" in out and "Axon" in out


def test_suite_contracts_are_grouped_by_default(db, capsys):
    run(db, "init")
    run(db, "import", SAMPLE, "--state", "IL")
    capsys.readouterr()

    run(db, "targets", "--today", "2026-09-04")
    grouped = capsys.readouterr().out
    run(db, "targets", "--today", "2026-09-04", "--ungrouped")
    ungrouped = capsys.readouterr().out
    # Springfield holds separate Tyler RMS and CAD contracts.
    assert grouped.count("Springfield") < ungrouped.count("Springfield")


def test_stage_and_state_filters(db, capsys):
    run(db, "init")
    run(db, "import", SAMPLE, "--state", "IL")
    capsys.readouterr()

    run(db, "targets", "--today", "2026-09-04", "--stage", "pitch_now")
    assert "Too early" not in capsys.readouterr().out

    run(db, "targets", "--today", "2026-09-04", "--state", "OH")
    assert "No targets matched" in capsys.readouterr().out


def test_json_output_is_machine_readable(db, capsys):
    import json

    run(db, "init")
    run(db, "import", SAMPLE, "--state", "IL")
    capsys.readouterr()
    run(db, "targets", "--today", "2026-09-04", "--json")
    payload = json.loads(capsys.readouterr().out)
    assert payload
    assert {"agency", "incumbent", "budget_deadline", "action"} <= set(payload[0])


def test_html_and_csv_reports_are_written(db, tmp_path, capsys):
    run(db, "init")
    run(db, "import", SAMPLE, "--state", "IL")
    capsys.readouterr()

    html_path = tmp_path / "out" / "report.html"
    csv_path = tmp_path / "out" / "report.csv"
    run(db, "report", "--today", "2026-09-04", "--format", "html", "-o", str(html_path))
    run(db, "report", "--today", "2026-09-04", "--format", "csv", "-o", str(csv_path))

    page = html_path.read_text()
    assert "<!doctype html>" in page
    assert "Pitch Calendar" in page
    assert '"opportunities"' in page
    assert csv_path.read_text().startswith("priority,stage,agency_name")


def test_foia_letters_are_generated_for_gaps(db, tmp_path, capsys):
    run(db, "init")
    # A contract with no expiration date is exactly the gap a request fills.
    gap = tmp_path / "gap.csv"
    gap.write_text(
        "Department,Vendor,Description,Term Thru\n"
        "Gapville Police Department,Tyler Technologies,Records management system,\n"
    )
    run(db, "import", str(gap), "--state", "OH")
    capsys.readouterr()

    outdir = tmp_path / "letters"
    assert run(db, "foia", "--out", str(outdir), "--name", "Jane Rep") == 0
    letters = list(outdir.glob("*.txt"))
    assert letters
    text = letters[0].read_text()
    assert "Ohio Public Records Act" in text
    assert "Jane Rep" in text


def test_foia_for_a_named_agency_uses_the_right_statute(db, capsys):
    run(db, "init")
    capsys.readouterr()
    run(db, "foia", "--agency", "Springfield Police Department", "--state", "IL")
    assert "Illinois Freedom of Information Act" in capsys.readouterr().out


def test_stats_and_taxonomy_commands(db, capsys):
    run(db, "init")
    run(db, "import", SAMPLE, "--state", "IL")
    capsys.readouterr()

    run(db, "stats", "--log")
    out = capsys.readouterr().out
    assert "contracts" in out and "Records Management System" in out

    run(db, "vendors", "--search", "motorola")
    assert "Motorola Solutions" in capsys.readouterr().out

    run(db, "categories")
    assert "Computer-Aided Dispatch" in capsys.readouterr().out


def test_min_value_filter(db, capsys):
    run(db, "init")
    run(db, "import", SAMPLE, "--state", "IL")
    capsys.readouterr()
    run(db, "targets", "--today", "2026-09-04", "--min-value", "5000000")
    assert "No targets matched" in capsys.readouterr().out
