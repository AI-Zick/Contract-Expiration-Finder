"""National council discovery."""

from pdcontracts.councils import (
    PLACES,
    Council,
    discover,
    probe_slug,
    slug_variants,
    to_source_entries,
)


# --- slug shapes ----------------------------------------------------------

def test_simple_city_slug():
    assert slug_variants("Denver", "CO")[0] == "denver"


def test_multiword_city_loses_spaces_and_punctuation():
    assert "sanantonio" in slug_variants("San Antonio", "TX")
    assert "stlouis" in slug_variants("St Louis", "MO")


def test_state_suffixed_variant_is_offered():
    assert "kansascitymo" in slug_variants("Kansas City", "MO")


def test_county_offers_both_with_and_without_the_word():
    variants = slug_variants("King County", "WA")
    assert "kingcounty" in variants
    assert "king" not in variants          # too short to be plausible
    assert "kingcountywa" in variants


def test_variants_are_unique_and_plausible():
    for name, state in PLACES[:80]:
        variants = slug_variants(name, state)
        assert len(variants) == len(set(variants))
        assert all(len(v) >= 3 for v in variants)


def test_place_list_covers_many_states():
    assert len({state for _, state in PLACES}) >= 40
    assert len(PLACES) > 300


# --- probing --------------------------------------------------------------

class Fake:
    """Answers for a fixed set of slugs, fails for everything else."""

    def __init__(self, live):
        self.live = set(live)
        self.calls = []

    def get_json(self, url, params=None, headers=None):
        slug = url.rstrip("/").split("/")[-2]
        self.calls.append(slug)
        if slug in self.live:
            return [{"BodyId": 1, "BodyName": "City Council"}]
        from pdcontracts.sources.base import FetchError

        raise FetchError("404 Not Found")


def test_probe_reports_a_live_slug():
    council = probe_slug("denver", "Denver", "CO", Fake(["denver"]))
    assert council.ok
    assert council.detail == "reachable"


def test_probe_reports_a_dead_slug_without_raising():
    council = probe_slug("nowhere", "Nowhere", "XX", Fake([]))
    assert not council.ok
    assert "404" in council.detail


def test_probe_treats_an_empty_response_as_not_usable():
    class Empty(Fake):
        def get_json(self, url, params=None, headers=None):
            return []

    assert not probe_slug("ghost", "Ghost", "XX", Empty([])).ok


def test_discovery_keeps_only_places_that_answer(monkeypatch):
    live = {"denver", "seattle"}

    def fake_probe(slug, name, state, fetcher=None):
        return Council(slug=slug, name=name, state=state, ok=slug in live)

    monkeypatch.setattr("pdcontracts.councils.probe_slug", fake_probe)
    found = discover([("Denver", "CO"), ("Seattle", "WA"), ("Nowhere", "XX")], workers=2)
    assert {c.slug for c in found} == {"denver", "seattle"}


def test_discovery_prefers_the_shortest_working_slug(monkeypatch):
    def fake_probe(slug, name, state, fetcher=None):
        return Council(slug=slug, name=name, state=state, ok=True)

    monkeypatch.setattr("pdcontracts.councils.probe_slug", fake_probe)
    found = discover([("Denver", "CO")], workers=2)
    assert [c.slug for c in found] == ["denver"]     # not "denverco"


def test_a_county_does_not_collapse_onto_its_city(monkeypatch):
    """'Los Angeles County' can generate the slug 'losangeles', which would
    collect the city's agendas twice."""
    def fake_probe(slug, name, state, fetcher=None):
        return Council(slug=slug, name=name, state=state, ok=True)

    monkeypatch.setattr("pdcontracts.councils.probe_slug", fake_probe)
    found = discover([("Los Angeles", "CA"), ("Los Angeles County", "CA")], workers=2)
    slugs = [c.slug for c in found]
    assert len(slugs) == len(set(slugs))


# --- config generation ----------------------------------------------------

def test_source_entries_are_valid_legistar_config():
    entry = to_source_entries([Council("denver", "Denver", "CO", ok=True)])[0]
    assert entry["type"] == "legistar"
    assert entry["client"] == "denver"
    assert entry["state"] == "CO"
    assert entry["enabled"] is True
    assert entry["jurisdiction"] == "Denver"
