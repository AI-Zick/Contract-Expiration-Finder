"""Collection orchestration.

Runs configured sources, normalizes what comes back, and merges it into the
store. One portal failing never stops the run -- every source reports its own
status into the collection log so coverage gaps are visible rather than silent.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Dict, List, Optional

from .config import load_settings, load_sources
from .models import Agency, Contract
from .normalize import normalize_agency_name, normalize_state
from .sources import registry
from .sources.base import HttpFetcher, SourceResult
from .store import Store


def build_source(spec: Dict[str, Any], settings: Dict[str, Any], fetcher=None):
    """Instantiate a connector from a config entry."""
    kind = spec.get("type") or spec.get("source")
    cls = registry.get(kind)
    if cls is None:
        raise ValueError(f"unknown source type '{kind}' (known: {sorted(registry)})")
    config = dict(spec)
    if kind == "socrata" and settings.get("socrata_app_token"):
        config.setdefault("app_token", settings["socrata_app_token"])
    return cls(config, fetcher)


def attach_agency_keys(contracts: List[Contract], store: Optional[Store] = None) -> None:
    """Resolve each contract to an agency key, creating agencies as needed."""
    known = store.get_agencies() if store else {}
    # Index existing agencies by normalized name within state so a contract
    # saying "Austin Police Dept" joins the "Austin Police Department" record.
    by_norm = {
        (a.state.upper(), normalize_agency_name(a.name)): key
        for key, a in known.items()
    }

    for contract in contracts:
        state = normalize_state(contract.state) or contract.state.upper()
        norm = normalize_agency_name(contract.agency_name)
        key = by_norm.get((state, norm))
        if key is None:
            agency = Agency(name=contract.agency_name, state=state)
            key = agency.key
            by_norm[(state, norm)] = key
            if store:
                store.upsert_agency(agency)
        contract.agency_key = key


def run_source(
    spec: Dict[str, Any],
    store: Store,
    settings: Dict[str, Any],
    fetcher=None,
) -> SourceResult:
    name = spec.get("name") or spec.get("type", "?")
    try:
        source = build_source(spec, settings, fetcher)
    except ValueError as exc:
        store.log_collection(str(spec.get("type")), "", 0, 0, "error", str(exc))
        return SourceResult(status="error", message=str(exc))

    try:
        result = source.collect()
    except Exception as exc:  # noqa: BLE001 - a bad portal must not abort the run
        store.log_collection(source.id, "", 0, 0, "error", f"{type(exc).__name__}: {exc}")
        return SourceResult(status="error", message=str(exc))

    min_conf = float(settings.get("min_classification_confidence", 0.0))
    kept = [
        c for c in result.contracts
        if c.is_software is not False and c.classification_confidence >= min_conf
    ]
    attach_agency_keys(kept, store)
    store.upsert_contracts(kept)
    store.log_collection(
        source.id, result.dataset or name, result.fetched, len(kept),
        result.status, result.message,
    )
    result.contracts = kept
    return result


def collect_all(
    store: Store,
    sources_path: str = "config/sources.yml",
    settings: Optional[Dict[str, Any]] = None,
    only: Optional[List[str]] = None,
    states: Optional[List[str]] = None,
    fetcher=None,
) -> List[Dict[str, Any]]:
    """Run every enabled source, returning a per-source summary."""
    settings = settings or load_settings()
    specs = load_sources(sources_path)
    fetcher = fetcher or HttpFetcher()
    summary: List[Dict[str, Any]] = []

    for spec in specs:
        name = spec.get("name") or spec.get("type", "?")
        if only and not any(
            token.lower() in (name.lower(), str(spec.get("type", "")).lower())
            for token in only
        ):
            continue
        if states and spec.get("state") and normalize_state(spec["state"]) not in [
            normalize_state(s) for s in states
        ]:
            continue

        result = run_source(spec, store, settings, fetcher)
        summary.append(
            {
                "name": name,
                "type": spec.get("type"),
                "status": result.status,
                "fetched": result.fetched,
                "kept": len(result.contracts),
                "message": result.message,
            }
        )
    return summary
