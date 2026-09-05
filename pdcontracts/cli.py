"""Command line interface."""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path
from typing import List, Optional

from . import __version__
from .config import load_settings, load_sources
from .foia import build_request
from .models import Agency, Contract
from .normalize import normalize_state
from .pipeline import build_source, collect_all, run_source
from .pitch import build_targets
from .report import (
    as_opportunities,
    console_table,
    detail,
    group_opportunities,
    to_csv,
)
from .sources import registry
from .sources.base import HttpFetcher
from .store import Store
from .web import render_dashboard
from .taxonomy import CATEGORIES, VENDORS


def _store(args) -> Store:
    settings = load_settings(args.settings)
    return Store(args.db or settings["database"])


def _focus(args, settings) -> Optional[List[str]]:
    if getattr(args, "all_categories", False):
        return None
    if getattr(args, "category", None):
        return list(args.category)
    return list(settings.get("focus_categories") or []) or None


# --- commands -------------------------------------------------------------

def cmd_init(args) -> int:
    settings = load_settings(args.settings)
    store = Store(args.db or settings["database"])
    print(f"database ready: {store.path}")

    seeds = Path(args.agencies or "config/agencies_seed.csv")
    if seeds.exists():
        import csv

        n = 0
        with seeds.open(encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                if not row.get("name"):
                    continue
                store.upsert_agency(
                    Agency(
                        name=row["name"],
                        state=normalize_state(row.get("state", "")),
                        city=row.get("city", ""),
                        county=row.get("county", ""),
                        ori=row.get("ori", ""),
                        agency_type=row.get("agency_type", ""),
                        sworn_officers=int(row["sworn_officers"])
                        if row.get("sworn_officers", "").strip().isdigit() else None,
                        population_served=int(row["population_served"])
                        if row.get("population_served", "").strip().isdigit() else None,
                        fiscal_year_start_month=int(row["fiscal_year_start_month"])
                        if row.get("fiscal_year_start_month", "").strip().isdigit() else None,
                        notes=row.get("notes", ""),
                    )
                )
                n += 1
        print(f"loaded {n} agencies from {seeds}")
    else:
        print(f"no agency seed file at {seeds} (optional)")

    sources = load_sources(args.sources)
    print(f"{len(sources)} enabled sources in {args.sources}")
    store.close()
    return 0


def cmd_doctor(args) -> int:
    """Probe every configured source and report which actually work.

    Portal dataset IDs change and cities take datasets offline, so this is the
    command to run before trusting a collection run.
    """
    settings = load_settings(args.settings)
    specs = load_sources(args.sources)
    if not specs:
        print(f"no sources configured in {args.sources}")
        return 1
    fetcher = HttpFetcher()
    failures = 0
    for spec in specs:
        name = spec.get("name") or spec.get("type", "?")
        try:
            source = build_source(spec, settings, fetcher)
            result = source.check()
        except Exception as exc:  # noqa: BLE001
            result = type("R", (), {"status": "error", "message": str(exc)})()
        marker = {"ok": "OK  ", "partial": "WARN", "empty": "WARN"}.get(result.status, "FAIL")
        if marker == "FAIL":
            failures += 1
        print(f"[{marker}] {name}: {result.message[:150]}")
    print(f"\n{len(specs) - failures}/{len(specs)} sources reachable")
    return 0 if failures == 0 else 2


def cmd_discover(args) -> int:
    """Search a Socrata domain for contract datasets."""
    from .sources.socrata import SocrataSource

    if args.all:
        return _discover_all(args)
    if not args.domain:
        print("give a domain, or --all to search every domain in sources.yml",
              file=sys.stderr)
        return 1

    source = SocrataSource({"domain": args.domain}, HttpFetcher())
    try:
        results = source.discover(limit=args.limit)
    except Exception as exc:  # noqa: BLE001
        print(f"discovery failed for {args.domain}: {exc}", file=sys.stderr)
        return 1
    if not results:
        print(f"no contract datasets found on {args.domain}")
        return 1
    for item in results:
        print(f"\n{item['name']}")
        print(f"  dataset : {item['dataset']}")
        print(f"  updated : {item['updated'][:10]}")
        if item["description"]:
            print(f"  about   : {item['description'][:120]}")
        cols = item.get("columns") or []
        if cols:
            print(f"  columns : {', '.join(cols[:10])}")
    print("\nAdd a promising dataset to config/sources.yml as:")
    print(f"  - name: {args.domain}\n    type: socrata\n    domain: {args.domain}"
          f"\n    dataset: <id above>\n    state: XX\n    jurisdiction: <City Name>")
    return 0


def _discover_all(args) -> int:
    """Search every Socrata domain in sources.yml that has no dataset pinned.

    This is the bootstrap step: dataset IDs are not shipped in config because
    they change, so this fills them in from the live catalog.
    """
    from .sources.socrata import SocrataSource

    specs = load_sources(args.sources)
    # load_sources drops disabled entries, so read the raw file instead --
    # unpinned domains are shipped disabled by design.
    import yaml

    raw = yaml.safe_load(Path(args.sources).read_text(encoding="utf-8")) or {}
    specs = raw.get("sources", raw if isinstance(raw, list) else [])
    pending = [
        s for s in specs
        if s.get("type") == "socrata" and not s.get("dataset")
    ]
    if not pending:
        print("every socrata source already has a dataset pinned")
        return 0

    fetcher = HttpFetcher()
    found = 0
    for spec in pending:
        domain = spec.get("domain", "")
        print(f"\n=== {spec.get('name', domain)} ({domain}) ===")
        try:
            results = SocrataSource({"domain": domain}, fetcher).discover(limit=args.limit)
        except Exception as exc:  # noqa: BLE001 - one dead portal must not stop the sweep
            print(f"  discovery failed: {exc}")
            continue
        if not results:
            print("  no contract datasets found")
            continue
        for item in results[:args.limit]:
            found += 1
            print(f"  {item['dataset']}  {item['name'][:64]}")
            cols = item.get("columns") or []
            if cols:
                print(f"      columns: {', '.join(cols[:8])}")
    print(f"\n{found} candidate datasets found. Paste ids into {args.sources}, "
          f"set enabled: true, then run: pdcontracts doctor")
    return 0


def cmd_collect(args) -> int:
    store = _store(args)
    settings = load_settings(args.settings)
    summary = collect_all(
        store,
        sources_path=args.sources,
        settings=settings,
        only=args.only,
        states=args.state,
    )
    if not summary:
        print("no sources ran (check --only / config/sources.yml)")
        store.close()
        return 1
    for row in summary:
        print(f"[{row['status']:7}] {row['name']:28} fetched={row['fetched']:<7} "
              f"kept={row['kept']:<6} {row['message'][:80]}")
    print(f"\ntotal contracts in database: {store.count()}")
    store.close()
    return 0


def cmd_import(args) -> int:
    store = _store(args)
    settings = load_settings(args.settings)
    overrides = {}
    for pair in args.column or []:
        if "=" in pair:
            key, value = pair.split("=", 1)
            overrides[key.strip()] = value.strip()

    spec = {
        "type": "csv",
        "name": args.file,
        "path": args.file,
        "state": args.state or "",
        "jurisdiction": args.jurisdiction or "",
        "source_name": args.source_name,
        "source_url": args.source_url or "",
        "columns": overrides,
        "assume_law_enforcement": not args.filter_law_enforcement,
    }
    result = run_source(spec, store, settings)
    print(f"[{result.status}] {result.message}")
    print(f"imported {len(result.contracts)} contracts; database total {store.count()}")
    store.close()
    return 0 if result.status in ("ok", "partial") else 1


def _load_targets(args, store, settings):
    categories = _focus(args, settings)
    contracts = store.contracts(
        states=args.state,
        categories=categories,
        software_only=True,
        min_confidence=args.min_confidence,
        vendor=args.vendor,
    )
    # Purchasing vehicles are not agency opportunities.
    contracts = [c for c in contracts if c.source != "cooperative"]
    if args.min_value:
        contracts = [
            c for c in contracts
            if (c.effective_annual_value or 0) >= args.min_value
        ]
    agencies = store.get_agencies()
    today = _dt.date.fromisoformat(args.today) if args.today else None
    targets = build_targets(contracts, agencies, today)
    if args.stage:
        targets = [t for t in targets if t.stage in args.stage]
    if settings.get("group_suite_opportunities", True) and not args.ungrouped:
        return group_opportunities(targets)
    return as_opportunities(targets)


def cmd_targets(args) -> int:
    store = _store(args)
    settings = load_settings(args.settings)
    opportunities = _load_targets(args, store, settings)

    if args.json:
        print(json.dumps(
            [
                {
                    "priority": o.priority, "stage": o.stage,
                    "agency": o.agency_name, "state": o.state,
                    "incumbent": o.incumbent, "systems": o.categories,
                    "annual_value": o.annual_value,
                    "expires": o.earliest_end.isoformat() if o.earliest_end else None,
                    "pitch_open": o.pitch_open.isoformat() if o.pitch_open else None,
                    "budget_deadline": o.budget_deadline.isoformat() if o.budget_deadline else None,
                    "action": o.action, "rationale": o.rationale,
                }
                for o in opportunities[:args.top]
            ],
            indent=2,
        ))
    elif args.detail:
        for opp in opportunities[:args.top]:
            print(detail(opp))
            print()
    else:
        print(console_table(opportunities, limit=args.top))
    store.close()
    return 0


def cmd_report(args) -> int:
    store = _store(args)
    settings = load_settings(args.settings)
    opportunities = _load_targets(args, store, settings)

    categories = _focus(args, settings)
    today = _dt.date.fromisoformat(args.today) if args.today else None
    if args.format == "html":
        content = render_dashboard(
            opportunities,
            focus=categories,
            today=today,
            standalone=True,
            sample=bool(args.sample_note),
            sample_note=args.sample_note or "",
        )
    elif args.format == "csv":
        content = to_csv(opportunities)
    else:
        content = console_table(opportunities, limit=args.top)

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(content, encoding="utf-8")
        print(f"wrote {args.out} ({len(opportunities)} opportunities)")
    else:
        print(content)
    store.close()
    return 0


def cmd_serve(args) -> int:
    """Open the pipeline as a local web dashboard."""
    from .server import serve

    settings = load_settings(args.settings)
    db_path = args.db or settings["database"]

    def builder():
        # A fresh store per request so a collection run in another terminal is
        # picked up on refresh rather than requiring a restart.
        store = Store(db_path)
        try:
            opportunities = _load_targets(args, store, settings)
            focus = _focus(args, settings) or []
            today = _dt.date.fromisoformat(args.today) if args.today else _dt.date.today()
            return opportunities, focus, today
        finally:
            store.close()

    serve(builder, host=args.host, port=args.port,
          open_browser=not args.no_browser, quiet=args.quiet)
    return 0


def cmd_foia(args) -> int:
    store = _store(args)
    settings = load_settings(args.settings)
    targets: List[tuple] = []

    if args.agency:
        # --state is nargs="*", so it arrives as a list; citing the right
        # statute is the difference between a request that gets processed and
        # one that gets ignored.
        state_arg = args.state[0] if isinstance(args.state, list) and args.state else (
            args.state or ""
        )
        targets.append((args.agency, normalize_state(state_arg)))
    else:
        # Agencies we know exist but have no expiration date for -- exactly the
        # gap a records request fills.
        categories = _focus(args, settings)
        agencies = store.get_agencies()
        seen = set()
        for contract in store.contracts(states=args.state, categories=categories):
            if contract.end_date:
                continue
            key = (contract.agency_name, contract.state)
            if key in seen:
                continue
            seen.add(key)
            targets.append(key)
        if args.include_all:
            for agency in agencies.values():
                key = (agency.name, agency.state)
                if key not in seen:
                    targets.append(key)
                    seen.add(key)

    if not targets:
        print("no agencies need a records request (all have expiration dates)")
        store.close()
        return 0

    outdir = Path(args.out) if args.out else None
    if outdir:
        outdir.mkdir(parents=True, exist_ok=True)

    for agency_name, state in targets[:args.limit]:
        letter = build_request(
            agency=agency_name,
            state=state,
            requester_name=args.name or "",
            requester_org=args.org or "",
            requester_email=args.email or "",
            requester_phone=args.phone or "",
        )
        if outdir:
            slug = "".join(
                ch if ch.isalnum() else "_" for ch in agency_name.lower()
            ).strip("_")[:60]
            path = outdir / f"{state or 'xx'}_{slug}.txt"
            path.write_text(letter, encoding="utf-8")
        else:
            print(letter)
            print("=" * 78)
    if outdir:
        print(f"wrote {min(len(targets), args.limit)} letters to {outdir}")
    store.close()
    return 0


def cmd_vehicles(args) -> int:
    store = _store(args)
    rows = [c for c in store.contracts(software_only=False) if c.source == "cooperative"]
    if not rows:
        print("no cooperative purchasing vehicles loaded "
              "(run: pdcontracts collect --only cooperative)")
        store.close()
        return 1
    print(f"{'CO-OP':34} {'VENDOR':26} {'EXPIRES':10}  DESCRIPTION")
    print("-" * 100)
    for row in sorted(rows, key=lambda c: (c.end_date or _dt.date.max)):
        print(f"{row.agency_name[:34]:34} {row.vendor_canonical[:26]:26} "
              f"{row.end_date.isoformat() if row.end_date else 'unverified':10}  "
              f"{row.description[:38]}")
    store.close()
    return 0


def cmd_stats(args) -> int:
    store = _store(args)
    stats = store.stats()
    print(f"contracts        : {stats['total']}")
    print(f"with expiration  : {stats['with_expiration']}")
    print(f"agencies         : {stats['agencies']}")
    print("\nby source:")
    for key, value in stats["by_source"].items():
        print(f"  {key:24} {value}")
    print("\nby category:")
    for key, value in stats["by_category"].items():
        label = CATEGORIES[key].label if key in CATEGORIES else key
        print(f"  {label:38} {value}")
    print("\nby state (top 15):")
    for key, value in list(stats["by_state"].items())[:15]:
        print(f"  {key:4} {value}")
    if args.log:
        print("\nrecent collection runs:")
        for row in store.collection_log(15):
            print(f"  {row['ran_at']} {row['source']:14} {row['status']:8} "
                  f"fetched={row['fetched']:<6} kept={row['kept']:<6} {row['message'][:60]}")
    store.close()
    return 0


def cmd_vendors(args) -> int:
    query = (args.search or "").lower()
    for vendor in VENDORS:
        blob = " ".join([vendor.canonical] + vendor.aliases + vendor.categories).lower()
        if query and query not in blob:
            continue
        cats = ", ".join(
            CATEGORIES[c].label if c in CATEGORIES else c for c in vendor.categories
        )
        print(f"{vendor.canonical:30} {cats}")
        if vendor.notes:
            print(f"{'':30} note: {vendor.notes}")
    return 0


def cmd_categories(args) -> int:
    print(f"{'KEY':18} {'LABEL':40} {'TERM':>6} {'STICK':>6} {'LEAD':>5}")
    print("-" * 80)
    for cat in CATEGORIES.values():
        print(f"{cat.key:18} {cat.label:40} {cat.typical_term_months:>4}mo "
              f"{cat.stickiness:>5}/5 {cat.lead_months:>3}mo")
    return 0


# --- parser ---------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pdcontracts",
        description="Find expiring police software contracts and rank who/when to pitch.",
    )
    parser.add_argument("--version", action="version", version=f"pdcontracts {__version__}")
    parser.add_argument("--db", help="SQLite path (overrides settings)")
    parser.add_argument("--settings", default="config/settings.yml")
    parser.add_argument("--sources", default="config/sources.yml")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="create the database and load agency seeds")
    p.add_argument("--agencies", help="agency seed CSV")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("doctor", help="check that configured sources are reachable")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("discover", help="find contract datasets on a Socrata domain")
    p.add_argument("domain", nargs="?", help="e.g. data.cityofchicago.org")
    p.add_argument("--all", action="store_true",
                   help="search every unpinned socrata domain in sources.yml")
    p.add_argument("--limit", type=int, default=15)
    p.set_defaults(func=cmd_discover)

    p = sub.add_parser("collect", help="run configured sources")
    p.add_argument("--only", nargs="*", help="source names or types to run")
    p.add_argument("--state", nargs="*", help="limit to these states")
    p.set_defaults(func=cmd_collect)

    p = sub.add_parser("import", help="import a CSV of contracts (FOIA responses, exports)")
    p.add_argument("file")
    p.add_argument("--state")
    p.add_argument("--jurisdiction", help="city/county name to qualify agency names")
    p.add_argument("--source-name", default="csv-import")
    p.add_argument("--source-url", default="")
    p.add_argument("--column", nargs="*", help="pin a mapping, e.g. end_date='Term Thru'")
    p.add_argument("--filter-law-enforcement", action="store_true",
                   help="drop rows that do not look like a police buyer")
    p.set_defaults(func=cmd_import)

    def add_target_filters(sp):
        sp.add_argument("--state", nargs="*")
        sp.add_argument("--category", nargs="*", help="override focus categories")
        sp.add_argument("--all-categories", action="store_true")
        sp.add_argument("--stage", nargs="*",
                        choices=["pitch_now", "procurement_live", "too_early",
                                 "late", "expired", "unknown"])
        sp.add_argument("--vendor", help="filter to an incumbent vendor")
        sp.add_argument("--min-value", type=float, default=0.0,
                        help="minimum annual value")
        sp.add_argument("--min-confidence", type=float, default=0.0)
        sp.add_argument("--top", type=int, default=40)
        sp.add_argument("--ungrouped", action="store_true",
                        help="one row per contract instead of per suite decision")
        sp.add_argument("--today", help="evaluate as of YYYY-MM-DD (for testing)")

    p = sub.add_parser("targets", help="ranked list of who to pitch and when")
    add_target_filters(p)
    p.add_argument("--detail", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_targets)

    p = sub.add_parser("report", help="write a CSV or HTML briefing")
    add_target_filters(p)
    p.add_argument("--format", choices=["html", "csv", "text"], default="html")
    p.add_argument("--out", "-o")
    p.add_argument("--sample-note", default="",
                   help="mark the export as sample data with this caption")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("serve", help="open the pipeline as a local web dashboard")
    add_target_filters(p)
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--host", default="127.0.0.1",
                   help="bind address; localhost by default")
    p.add_argument("--no-browser", action="store_true")
    p.add_argument("--quiet", action="store_true")
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("foia", help="generate public records request letters")
    p.add_argument("--agency", help="single agency name")
    p.add_argument("--state", nargs="*")
    p.add_argument("--category", nargs="*")
    p.add_argument("--all-categories", action="store_true")
    p.add_argument("--include-all", action="store_true",
                   help="also write letters for agencies with no contracts at all")
    p.add_argument("--limit", type=int, default=25)
    p.add_argument("--out", help="directory to write letters into")
    p.add_argument("--name")
    p.add_argument("--org")
    p.add_argument("--email")
    p.add_argument("--phone")
    p.set_defaults(func=cmd_foia)

    p = sub.add_parser("vehicles", help="list cooperative purchasing vehicles")
    p.set_defaults(func=cmd_vehicles)

    p = sub.add_parser("stats", help="coverage statistics")
    p.add_argument("--log", action="store_true", help="include recent collection runs")
    p.set_defaults(func=cmd_stats)

    p = sub.add_parser("vendors", help="show the vendor taxonomy")
    p.add_argument("--search")
    p.set_defaults(func=cmd_vendors)

    p = sub.add_parser("categories", help="show product categories and their timing model")
    p.set_defaults(func=cmd_categories)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
