"""Find every city whose council agendas we can actually read.

Council agendas are the best source for RMS, CAD and MDT contracts, because
those buys clear the threshold that requires a public vote. Legistar (Granicus)
runs the agenda system for several hundred US cities and exposes a public read
API, but there is no directory of which cities are on it and no list of their
slugs.

So we probe. Slugs are derived from city and county names in a handful of
predictable shapes, every candidate is tried against a cheap endpoint, and the
ones that answer become sources. The whole sweep is a few hundred small
requests and it is the difference between seven cities and a national roster.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .sources.base import FetchError, HttpFetcher

API = "https://webapi.legistar.com/v1"
PROBE_TIMEOUT = 8


# Cities and counties worth probing, spread across all fifty states rather than
# only the largest metros -- mid-size agencies are where most displacement
# deals live. (name, state).
PLACES: List[Tuple[str, str]] = [
    ("New York", "NY"), ("Los Angeles", "CA"), ("Chicago", "IL"), ("Houston", "TX"),
    ("Phoenix", "AZ"), ("Philadelphia", "PA"), ("San Antonio", "TX"), ("San Diego", "CA"),
    ("Dallas", "TX"), ("San Jose", "CA"), ("Austin", "TX"), ("Jacksonville", "FL"),
    ("Fort Worth", "TX"), ("Columbus", "OH"), ("Charlotte", "NC"), ("Indianapolis", "IN"),
    ("San Francisco", "CA"), ("Seattle", "WA"), ("Denver", "CO"), ("Oklahoma City", "OK"),
    ("Nashville", "TN"), ("Washington", "DC"), ("El Paso", "TX"), ("Boston", "MA"),
    ("Portland", "OR"), ("Las Vegas", "NV"), ("Detroit", "MI"), ("Memphis", "TN"),
    ("Louisville", "KY"), ("Baltimore", "MD"), ("Milwaukee", "WI"), ("Albuquerque", "NM"),
    ("Tucson", "AZ"), ("Fresno", "CA"), ("Sacramento", "CA"), ("Mesa", "AZ"),
    ("Kansas City", "MO"), ("Atlanta", "GA"), ("Omaha", "NE"), ("Colorado Springs", "CO"),
    ("Raleigh", "NC"), ("Virginia Beach", "VA"), ("Long Beach", "CA"), ("Miami", "FL"),
    ("Oakland", "CA"), ("Minneapolis", "MN"), ("Tulsa", "OK"), ("Bakersfield", "CA"),
    ("Wichita", "KS"), ("Arlington", "TX"), ("Aurora", "CO"), ("Tampa", "FL"),
    ("New Orleans", "LA"), ("Cleveland", "OH"), ("Honolulu", "HI"), ("Anaheim", "CA"),
    ("Lexington", "KY"), ("Stockton", "CA"), ("Corpus Christi", "TX"), ("Henderson", "NV"),
    ("Riverside", "CA"), ("Newark", "NJ"), ("Saint Paul", "MN"), ("Santa Ana", "CA"),
    ("Cincinnati", "OH"), ("Irvine", "CA"), ("Orlando", "FL"), ("Pittsburgh", "PA"),
    ("St Louis", "MO"), ("Greensboro", "NC"), ("Jersey City", "NJ"), ("Anchorage", "AK"),
    ("Lincoln", "NE"), ("Plano", "TX"), ("Durham", "NC"), ("Buffalo", "NY"),
    ("Chandler", "AZ"), ("Chula Vista", "CA"), ("Toledo", "OH"), ("Madison", "WI"),
    ("Gilbert", "AZ"), ("Reno", "NV"), ("Fort Wayne", "IN"), ("North Las Vegas", "NV"),
    ("St Petersburg", "FL"), ("Lubbock", "TX"), ("Irving", "TX"), ("Laredo", "TX"),
    ("Winston Salem", "NC"), ("Chesapeake", "VA"), ("Glendale", "AZ"), ("Scottsdale", "AZ"),
    ("Garland", "TX"), ("Boise", "ID"), ("Norfolk", "VA"), ("Spokane", "WA"),
    ("Fremont", "CA"), ("Richmond", "VA"), ("Santa Clarita", "CA"), ("San Bernardino", "CA"),
    ("Baton Rouge", "LA"), ("Hialeah", "FL"), ("Tacoma", "WA"), ("Modesto", "CA"),
    ("Port St Lucie", "FL"), ("Huntsville", "AL"), ("Des Moines", "IA"), ("Moreno Valley", "CA"),
    ("Fontana", "CA"), ("Frisco", "TX"), ("Rochester", "NY"), ("Yonkers", "NY"),
    ("Fayetteville", "NC"), ("Worcester", "MA"), ("Columbus", "GA"), ("Cape Coral", "FL"),
    ("McKinney", "TX"), ("Little Rock", "AR"), ("Oxnard", "CA"), ("Amarillo", "TX"),
    ("Augusta", "GA"), ("Salt Lake City", "UT"), ("Montgomery", "AL"), ("Birmingham", "AL"),
    ("Grand Rapids", "MI"), ("Grand Prairie", "TX"), ("Overland Park", "KS"),
    ("Tallahassee", "FL"), ("Huntington Beach", "CA"), ("Sioux Falls", "SD"),
    ("Peoria", "AZ"), ("Knoxville", "TN"), ("Glendale", "CA"), ("Vancouver", "WA"),
    ("Providence", "RI"), ("Akron", "OH"), ("Brownsville", "TX"), ("Mobile", "AL"),
    ("Newport News", "VA"), ("Tempe", "AZ"), ("Shreveport", "LA"), ("Chattanooga", "TN"),
    ("Fort Lauderdale", "FL"), ("Aurora", "IL"), ("Elk Grove", "CA"), ("Ontario", "CA"),
    ("Salem", "OR"), ("Cary", "NC"), ("Santa Rosa", "CA"), ("Rancho Cucamonga", "CA"),
    ("Eugene", "OR"), ("Oceanside", "CA"), ("Clarksville", "TN"), ("Garden Grove", "CA"),
    ("Lancaster", "CA"), ("Springfield", "MO"), ("Pembroke Pines", "FL"), ("Fort Collins", "CO"),
    ("Palmdale", "CA"), ("Salinas", "CA"), ("Hayward", "CA"), ("Corona", "CA"),
    ("Paterson", "NJ"), ("Murfreesboro", "TN"), ("Macon", "GA"), ("Lakewood", "CO"),
    ("Killeen", "TX"), ("Springfield", "MA"), ("Alexandria", "VA"), ("Kansas City", "KS"),
    ("Sunnyvale", "CA"), ("Hollywood", "FL"), ("Roseville", "CA"), ("Charleston", "SC"),
    ("Escondido", "CA"), ("Joliet", "IL"), ("Jackson", "MS"), ("Bellevue", "WA"),
    ("Surprise", "AZ"), ("Naperville", "IL"), ("Pasadena", "TX"), ("Pomona", "CA"),
    ("Bridgeport", "CT"), ("Denton", "TX"), ("Rockford", "IL"), ("Mesquite", "TX"),
    ("Savannah", "GA"), ("Syracuse", "NY"), ("McAllen", "TX"), ("Torrance", "CA"),
    ("Olathe", "KS"), ("Visalia", "CA"), ("Thornton", "CO"), ("Fullerton", "CA"),
    ("Gainesville", "FL"), ("Waco", "TX"), ("West Valley City", "UT"), ("Warren", "MI"),
    ("Hampton", "VA"), ("Dayton", "OH"), ("Columbia", "SC"), ("Orange", "CA"),
    ("Cedar Rapids", "IA"), ("Stamford", "CT"), ("Victorville", "CA"), ("Pasadena", "CA"),
    ("Elizabeth", "NJ"), ("New Haven", "CT"), ("Miramar", "FL"), ("Kent", "WA"),
    ("Sterling Heights", "MI"), ("Carrollton", "TX"), ("Coral Springs", "FL"),
    ("Midland", "TX"), ("Norman", "OK"), ("Athens", "GA"), ("Santa Clara", "CA"),
    ("Columbia", "MO"), ("Fargo", "ND"), ("Pearland", "TX"), ("Simi Valley", "CA"),
    ("Topeka", "KS"), ("Meridian", "ID"), ("Allentown", "PA"), ("Thousand Oaks", "CA"),
    ("Abilene", "TX"), ("Vallejo", "CA"), ("Concord", "CA"), ("Round Rock", "TX"),
    ("Arvada", "CO"), ("Clovis", "CA"), ("Palm Bay", "FL"), ("Independence", "MO"),
    ("Lafayette", "LA"), ("Ann Arbor", "MI"), ("Rochester", "MN"), ("Hartford", "CT"),
    ("College Station", "TX"), ("Fairfield", "CA"), ("Wilmington", "NC"), ("North Charleston", "SC"),
    ("Billings", "MT"), ("West Palm Beach", "FL"), ("Berkeley", "CA"), ("Cambridge", "MA"),
    ("Clearwater", "FL"), ("West Jordan", "UT"), ("Evansville", "IN"), ("Richardson", "TX"),
    ("Broken Arrow", "OK"), ("Richmond", "CA"), ("League City", "TX"), ("Manchester", "NH"),
    ("Lakeland", "FL"), ("Carlsbad", "CA"), ("Antioch", "CA"), ("Westminster", "CO"),
    ("High Point", "NC"), ("Provo", "UT"), ("Lowell", "MA"), ("Elgin", "IL"),
    ("Waterbury", "CT"), ("Springfield", "IL"), ("Gresham", "OR"), ("Murrieta", "CA"),
    ("Lewisville", "TX"), ("Las Cruces", "NM"), ("Lansing", "MI"), ("Beaumont", "TX"),
    ("Odessa", "TX"), ("Pueblo", "CO"), ("Peoria", "IL"), ("Downey", "CA"),
    ("Burbank", "CA"), ("South Bend", "IN"), ("Sandy Springs", "GA"), ("El Monte", "CA"),
    ("Renton", "WA"), ("Davenport", "IA"), ("Everett", "WA"), ("Wichita Falls", "TX"),
    ("Green Bay", "WI"), ("Daly City", "CA"), ("Boulder", "CO"), ("Sparks", "NV"),
    ("Tyler", "TX"), ("San Mateo", "CA"), ("Norwalk", "CA"), ("Rialto", "CA"),
    ("Vista", "CA"), ("Chico", "CA"), ("Longmont", "CO"), ("Flint", "MI"),
    ("Kenosha", "WI"), ("Roanoke", "VA"), ("Portsmouth", "VA"), ("Trenton", "NJ"),
    ("Scranton", "PA"), ("Erie", "PA"), ("Bend", "OR"), ("Asheville", "NC"),
    ("Duluth", "MN"), ("Cheyenne", "WY"), ("Burlington", "VT"), ("Portland", "ME"),
    ("Dover", "DE"), ("Charleston", "WV"), ("Bismarck", "ND"), ("Missoula", "MT"),
    ("Casper", "WY"), ("Rapid City", "SD"), ("Sioux City", "IA"), ("Fayetteville", "AR"),
    ("Bellingham", "WA"), ("Olympia", "WA"), ("Santa Monica", "CA"), ("Palo Alto", "CA"),
    ("Sunrise", "FL"), ("Plantation", "FL"), ("Boca Raton", "FL"), ("Davie", "FL"),
    ("Alameda", "CA"), ("Napa", "CA"), ("Petaluma", "CA"), ("Redwood City", "CA"),
    ("Mountain View", "CA"), ("Milpitas", "CA"), ("Union City", "CA"), ("Hoboken", "NJ"),
    # Counties, which run sheriff's offices -- often larger buyers than cities.
    ("King County", "WA"), ("Los Angeles County", "CA"), ("Cook County", "IL"),
    ("Harris County", "TX"), ("Maricopa County", "AZ"), ("Miami Dade County", "FL"),
    ("Orange County", "CA"), ("San Diego County", "CA"), ("Riverside County", "CA"),
    ("Clark County", "NV"), ("Wayne County", "MI"), ("Santa Clara County", "CA"),
    ("Broward County", "FL"), ("Alameda County", "CA"), ("Sacramento County", "CA"),
    ("Bexar County", "TX"), ("Tarrant County", "TX"), ("Travis County", "TX"),
    ("Fulton County", "GA"), ("Mecklenburg County", "NC"), ("Montgomery County", "MD"),
    ("Fairfax County", "VA"), ("Prince Georges County", "MD"), ("Hennepin County", "MN"),
    ("Franklin County", "OH"), ("Cuyahoga County", "OH"), ("Allegheny County", "PA"),
    ("Pima County", "AZ"), ("Contra Costa County", "CA"), ("Salt Lake County", "UT"),
    ("Pinellas County", "FL"), ("Hillsborough County", "FL"), ("Orange County", "FL"),
    ("Palm Beach County", "FL"), ("Duval County", "FL"), ("Marion County", "IN"),
    ("Multnomah County", "OR"), ("Snohomish County", "WA"), ("Pierce County", "WA"),
    ("Jefferson County", "CO"), ("Arapahoe County", "CO"), ("Adams County", "CO"),
    ("Douglas County", "NE"), ("Johnson County", "KS"), ("Sedgwick County", "KS"),
    ("Oakland County", "MI"), ("Macomb County", "MI"), ("Milwaukee County", "WI"),
    ("Dane County", "WI"), ("Ramsey County", "MN"), ("St Louis County", "MO"),
    ("Jackson County", "MO"), ("Shelby County", "TN"), ("Davidson County", "TN"),
    ("Knox County", "TN"), ("Jefferson County", "KY"), ("Baltimore County", "MD"),
    ("Anne Arundel County", "MD"), ("Howard County", "MD"), ("Loudoun County", "VA"),
    ("Prince William County", "VA"), ("Chesterfield County", "VA"), ("Henrico County", "VA"),
    ("Wake County", "NC"), ("Guilford County", "NC"), ("Durham County", "NC"),
    ("Charleston County", "SC"), ("Greenville County", "SC"), ("Richland County", "SC"),
    ("Gwinnett County", "GA"), ("Cobb County", "GA"), ("DeKalb County", "GA"),
    ("Bernalillo County", "NM"), ("El Paso County", "CO"), ("Washoe County", "NV"),
    ("Suffolk County", "NY"), ("Nassau County", "NY"), ("Westchester County", "NY"),
    ("Erie County", "NY"), ("Monroe County", "NY"), ("Bergen County", "NJ"),
    ("Essex County", "NJ"), ("Middlesex County", "NJ"), ("Hudson County", "NJ"),
]


def slug_variants(name: str, state: str) -> List[str]:
    """Plausible Legistar slugs for a place.

    Slugs are usually the bare name, sometimes with the state appended, and
    counties sometimes drop or keep the word 'county'.
    """
    base = re.sub(r"[^a-z0-9]", "", name.lower())
    variants = [base, f"{base}{state.lower()}"]
    if base.endswith("county"):
        # The bare stem is deliberately not probed: "king", "orange" and
        # "wayne" would match whichever unrelated jurisdiction happens to own
        # that slug, and the result would be filed under the wrong county.
        stem = base[: -len("county")]
        variants += [f"{stem}county{state.lower()}", f"{stem}{state.lower()}"]
    # Deduplicate, keep order, drop anything implausibly short.
    seen, out = set(), []
    for v in variants:
        if len(v) >= 3 and v not in seen:
            seen.add(v)
            out.append(v)
    return out


@dataclass
class Council:
    slug: str
    name: str
    state: str
    ok: bool = False
    detail: str = ""


def probe_slug(slug: str, name: str, state: str,
               fetcher: Optional[HttpFetcher] = None) -> Council:
    """Ask Legistar whether a slug exists, as cheaply as possible."""
    # A fresh fetcher per probe: requests Sessions are not safe to share across
    # the thread pool this runs in.
    fetcher = fetcher or HttpFetcher(timeout=PROBE_TIMEOUT, retries=1, delay=0)
    council = Council(slug=slug, name=name, state=state)
    try:
        rows = fetcher.get_json(f"{API}/{slug}/bodies", params={"$top": 1})
    except FetchError as exc:
        council.detail = str(exc)[:120]
        return council
    except Exception as exc:  # noqa: BLE001
        council.detail = f"{type(exc).__name__}: {exc}"[:120]
        return council
    council.ok = bool(rows)
    council.detail = "reachable" if rows else "empty"
    return council


def discover(
    places: Optional[Sequence[Tuple[str, str]]] = None,
    workers: int = 12,
    limit: Optional[int] = None,
    progress=None,
) -> List[Council]:
    """Probe every candidate slug and return the ones that answer.

    Only the first working variant per place is kept, so a city does not get
    collected twice under two spellings.
    """
    places = list(places or PLACES)
    if limit:
        places = places[:limit]

    jobs = []
    for name, state in places:
        for slug in slug_variants(name, state):
            jobs.append((slug, name, state))

    found: Dict[Tuple[str, str], Council] = {}
    tried = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(probe_slug, s, n, st): (s, n, st) for s, n, st in jobs}
        for future in as_completed(futures):
            tried += 1
            council = future.result()
            if progress and tried % 50 == 0:
                progress(tried, len(jobs), len(found))
            if not council.ok:
                continue
            key = (council.name, council.state)
            # Prefer the shortest working slug -- that is the canonical one.
            if key not in found or len(council.slug) < len(found[key].slug):
                found[key] = council

    # A county's variants can collapse onto the city's slug ("Los Angeles
    # County" -> "losangeles"), which would collect the same agendas twice.
    by_slug: Dict[str, Council] = {}
    for council in found.values():
        seen = by_slug.get(council.slug)
        if seen is None or len(council.name) < len(seen.name):
            by_slug[council.slug] = council
    return sorted(by_slug.values(), key=lambda c: (c.state, c.name))


def to_source_entries(councils: Iterable[Council]) -> List[dict]:
    """Turn discovered councils into sources.yml entries."""
    entries = []
    for c in councils:
        entries.append({
            "name": f"leg-{c.slug}",
            "type": "legistar",
            "enabled": True,
            "client": c.slug,
            "state": c.state,
            "jurisdiction": c.name,
            "years_back": 8,
            "max_pages": 2,
        })
    return entries
