"""Turn a fresh clone into a working pipeline in one command.

Socrata dataset IDs are not shipped in config because they change and cities
retire datasets. That is correct but it leaves a chore: discover candidates,
work out which ones actually hold contracts, paste ids into YAML. This does
that automatically.

For each configured domain it searches the catalog, probes each candidate
dataset with a real request, scores how usable it is, and pins the winner.
Scoring is the interesting part -- a dataset is only useful here if the column
mapper can find a vendor and an expiration in it, and if it actually contains
law-enforcement rows.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .columnmap import map_columns
from .normalize import looks_like_law_enforcement
from .sources.base import FetchError, HttpFetcher
from .sources.socrata import SocrataSource

# A dataset without a vendor column cannot produce a contract at all.
REQUIRED = "vendor"
# Points per useful mapped field. An expiration is worth more than everything
# else combined -- without one there is no pitch window to compute.
WEIGHTS = {
    "end_date": 45,
    "vendor": 25,
    "agency": 12,
    "description": 8,
    "start_date": 6,
    "total_value": 5,
    "annual_value": 5,
    "contract_number": 3,
}
LE_BONUS = 20          # dataset actually contains police rows
MIN_SCORE = 60


@dataclass
class Probe:
    domain: str
    dataset: str
    name: str
    score: int = 0
    mapped: Dict[str, str] = field(default_factory=dict)
    rows_sampled: int = 0
    le_rows: int = 0
    error: str = ""

    @property
    def usable(self) -> bool:
        if self.error or REQUIRED not in self.mapped:
            return False
        # Without a date there is no pitch window to compute, whatever else the
        # dataset carries. An expiration is ideal; a start date lets the
        # category's typical term infer one.
        if not ({"end_date", "start_date"} & set(self.mapped)):
            return False
        return self.score >= MIN_SCORE

    def summary(self) -> str:
        if self.error:
            return f"unreachable: {self.error[:70]}"
        have = [f for f in ("end_date", "vendor", "agency") if f in self.mapped]
        missing = [f for f in ("end_date", "vendor", "agency") if f not in self.mapped]
        bits = [f"score {self.score}", "has " + "+".join(have) if have else "nothing mapped"]
        if missing:
            bits.append("no " + "/".join(missing))
        bits.append(f"{self.le_rows}/{self.rows_sampled} police rows")
        return "; ".join(bits)


def probe_dataset(source: SocrataSource, name: str = "") -> Probe:
    """Fetch a sample of a dataset and score how usable it is."""
    probe = Probe(domain=source.domain, dataset=source.dataset, name=name)
    try:
        rows = source._fetch_page(200, 0)
    except FetchError as exc:
        probe.error = str(exc)
        return probe
    except Exception as exc:  # noqa: BLE001 - a malformed portal is just unusable
        probe.error = f"{type(exc).__name__}: {exc}"
        return probe

    if not rows:
        probe.error = "dataset is empty"
        return probe

    probe.rows_sampled = len(rows)
    probe.mapped = map_columns(rows[0].keys(), rows)
    probe.score = sum(w for f, w in WEIGHTS.items() if f in probe.mapped)

    agency_col = probe.mapped.get("agency")
    desc_col = probe.mapped.get("description")
    for row in rows:
        if looks_like_law_enforcement(
            str(row.get(agency_col, "")) if agency_col else "",
            str(row.get(desc_col, "")) if desc_col else "",
        ):
            probe.le_rows += 1
    if probe.le_rows:
        probe.score += LE_BONUS
    return probe


def discover_and_probe(
    domain: str,
    fetcher: Optional[HttpFetcher] = None,
    limit: int = 6,
    app_token: str = "",
) -> List[Probe]:
    """Find contract datasets on a domain and probe each one."""
    fetcher = fetcher or HttpFetcher()
    finder = SocrataSource({"domain": domain, "app_token": app_token}, fetcher)
    try:
        candidates = finder.discover(limit=limit)
    except FetchError as exc:
        return [Probe(domain=domain, dataset="", name="", error=str(exc))]

    probes = []
    for item in candidates:
        if not item.get("dataset"):
            continue
        source = SocrataSource(
            {"domain": domain, "dataset": item["dataset"], "app_token": app_token},
            fetcher,
        )
        probes.append(probe_dataset(source, item.get("name", "")))
    probes.sort(key=lambda p: p.score, reverse=True)
    return probes


def pin_dataset(text: str, name: str, dataset: str) -> str:
    """Write a discovered dataset id back into sources.yml.

    Edits the one line for that source rather than re-serializing the file, so
    comments and formatting survive.
    """
    out = []
    for line in text.splitlines(keepends=True):
        if re.search(r"\bname:\s*%s\b" % re.escape(name), line):
            line = re.sub(r'dataset:\s*"[^"]*"', f'dataset: "{dataset}"', line)
            line = re.sub(r"dataset:\s*''", f'dataset: "{dataset}"', line)
            line = re.sub(r"\benabled:\s*false\b", "enabled: true", line)
        out.append(line)
    return "".join(out)


def bootstrap(
    sources_path: str,
    fetcher: Optional[HttpFetcher] = None,
    limit: int = 6,
    app_token: str = "",
    write: bool = False,
    only: Optional[List[str]] = None,
) -> Tuple[List[Tuple[str, Probe]], str]:
    """Probe every unpinned Socrata domain; optionally pin the winners.

    Returns (results, updated_yaml_text).
    """
    import yaml

    text = Path(sources_path).read_text(encoding="utf-8")
    raw = yaml.safe_load(text) or {}
    specs = raw.get("sources", raw if isinstance(raw, list) else [])
    pending = [
        s for s in specs
        if s.get("type") == "socrata" and not s.get("dataset") and s.get("domain")
        and (not only or s.get("name") in only)
    ]

    fetcher = fetcher or HttpFetcher()
    results: List[Tuple[str, Probe]] = []
    for spec in pending:
        name = spec.get("name") or spec["domain"]
        probes = discover_and_probe(spec["domain"], fetcher, limit, app_token)
        best = next((p for p in probes if p.usable), None)
        results.append((name, best or (probes[0] if probes else
                        Probe(spec["domain"], "", "", error="no datasets found"))))
        if write and best:
            text = pin_dataset(text, name, best.dataset)

    if write:
        Path(sources_path).write_text(text, encoding="utf-8")
    return results, text
