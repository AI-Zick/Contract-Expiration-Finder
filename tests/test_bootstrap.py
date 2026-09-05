"""Automatic dataset discovery, probing and pinning."""

from conftest import FakeFetcher

from pdcontracts.bootstrap import bootstrap, discover_and_probe, pin_dataset, probe_dataset
from pdcontracts.sources.socrata import SocrataSource

GOOD = [{"vendor_name": "AXON ENTERPRISE INC", "department": "POLICE",
         "short_description": "Body camera program", "start_date": "2024-01-01",
         "end_date": "2028-12-31", "contract_amount": "1750000",
         "purchase_order_number": "PO-1"}]
NO_END = [{"vendor_name": "AXON", "department": "POLICE", "amount": "100"}]
NO_POLICE = [{"vendor_name": "GREEN THUMB", "department": "PARKS",
              "end_date": "2027-01-01", "contract_amount": "5000"}]
UNRELATED = [{"tree_species": "oak", "planted_on": "2020-01-01"}]


def probe(rows):
    fetcher = FakeFetcher(pages={"/resource/": [rows]})
    return probe_dataset(SocrataSource({"domain": "d.gov", "dataset": "ab12-cd34"}, fetcher))


def test_a_real_contract_dataset_is_usable():
    p = probe(GOOD)
    assert p.usable
    assert p.mapped["end_date"] == "end_date"
    assert p.le_rows == 1


def test_dataset_without_an_expiration_scores_too_low():
    """No expiration means no pitch window, so the dataset is not worth pinning."""
    p = probe(NO_END)
    assert "end_date" not in p.mapped
    assert not p.usable


def test_dataset_with_no_police_rows_is_penalised():
    assert probe(NO_POLICE).le_rows == 0


def test_unrelated_dataset_is_rejected():
    p = probe(UNRELATED)
    assert not p.usable
    assert "vendor" not in p.mapped


def test_empty_dataset_is_reported_not_raised():
    p = probe([])
    assert not p.usable
    assert "empty" in p.error


def test_unreachable_dataset_is_reported_not_raised():
    class Dead(FakeFetcher):
        def get_json(self, url, params=None, headers=None):
            from pdcontracts.sources.base import FetchError

            raise FetchError("404")

    p = probe_dataset(SocrataSource({"domain": "d", "dataset": "x"}, Dead()))
    assert not p.usable
    assert "404" in p.error


def test_probe_summary_is_human_readable():
    assert "score" in probe(GOOD).summary()
    assert "police rows" in probe(GOOD).summary()


def test_discovery_probes_and_ranks_candidates():
    catalog = {"results": [
        {"resource": {"id": "aaaa-1111", "name": "Tree inventory"}},
        {"resource": {"id": "bbbb-2222", "name": "Contracts"}},
    ]}
    fetcher = FakeFetcher(
        responses={"catalog": catalog},
        pages={"/resource/": [UNRELATED, GOOD]},
    )
    probes = discover_and_probe("d.gov", fetcher, limit=2)
    assert probes[0].dataset == "bbbb-2222"   # the usable one ranks first
    assert probes[0].usable


# --- pinning --------------------------------------------------------------

YAML = '''sources:
  # a comment that must survive
  - {name: chicago, type: socrata, enabled: false, domain: data.cityofchicago.org, dataset: "", state: IL}
  - {name: austin,  type: socrata, enabled: false, domain: data.austintexas.gov,   dataset: "", state: TX}
'''


def test_pinning_sets_the_id_and_enables_the_source():
    out = pin_dataset(YAML, "chicago", "ab12-cd34")
    assert 'dataset: "ab12-cd34"' in out
    assert "name: chicago, type: socrata, enabled: true" in out


def test_pinning_leaves_other_sources_and_comments_alone():
    out = pin_dataset(YAML, "chicago", "ab12-cd34")
    assert "a comment that must survive" in out
    assert "name: austin,  type: socrata, enabled: false" in out


def test_bootstrap_dry_run_does_not_write(tmp_path):
    path = tmp_path / "sources.yml"
    path.write_text(YAML)
    catalog = {"results": [{"resource": {"id": "bbbb-2222", "name": "Contracts"}}]}
    fetcher = FakeFetcher(responses={"catalog": catalog},
                          pages={"/resource/": [GOOD, GOOD]})
    results, text = bootstrap(str(path), fetcher, limit=1)
    assert len(results) == 2
    assert path.read_text() == YAML          # untouched
    assert results[0][1].usable


def test_bootstrap_write_pins_every_domain(tmp_path):
    path = tmp_path / "sources.yml"
    path.write_text(YAML)
    catalog = {"results": [{"resource": {"id": "bbbb-2222", "name": "Contracts"}}]}
    fetcher = FakeFetcher(responses={"catalog": catalog},
                          pages={"/resource/": [GOOD, GOOD]})
    bootstrap(str(path), fetcher, limit=1, write=True)
    written = path.read_text()
    assert written.count('dataset: "bbbb-2222"') == 2
    assert "enabled: false" not in written


def test_bootstrap_skips_already_pinned_sources(tmp_path):
    path = tmp_path / "sources.yml"
    path.write_text(YAML.replace('dataset: ""', 'dataset: "zzzz-9999"', 1))
    fetcher = FakeFetcher(responses={"catalog": {"results": []}}, pages={})
    results, _ = bootstrap(str(path), fetcher)
    assert [n for n, _ in results] == ["austin"]
