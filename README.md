# Contract Expiration Finder

Finds police department software contracts that are coming up for renewal, and
tells your sales team **who to call and when**.

Built around one idea: government software is not bought when a contract
expires, it is bought when the money is appropriated — which happens 12 to 18
months earlier, on a fixed annual budget calendar. A pitch that lands after
that window is too late no matter how good the product is.

Default focus is **RMS, CAD, and MDT / mobile field reporting**. Other segments
are still collected (they show you the incumbent's whole footprint in an
agency) but targeting and reports focus on those three.

---

## Read this first: what the data actually looks like

There is no national database of local police software contracts, and any
vendor who sells you one is selling a partial scrape. Roughly 18,000 US law
enforcement agencies buy independently, and their contract data is scattered:

**These contracts are public records.** Nothing here scrapes anything private
or requires a vendor data subscription. The catch is that "public" does not
mean "in one place" — it means 18,000 agencies each publishing, or not
publishing, on their own terms.

| Where contracts live | Coverage | This tool |
|---|---|---|
| City council agendas (Legistar) | ~hundreds of cities, and the **best source for RMS/CAD/MDT** | Automated, no API key |
| Federal awards (USAspending.gov) | Federal LE agencies + DOJ grants to cities | Automated, no API key |
| City open-data portals (Socrata) | A few hundred large cities | Automated via `bootstrap` |
| State procurement portals | Varies wildly by state | Socrata states automated; others via CSV export |
| Cooperative purchasing vehicles | Thousands of agencies buy off these | Maintained CSV |
| **Everything else** | **The large majority of agencies** | **Records requests** |

The first row deserves emphasis for your use case. An RMS or CAD replacement
costs millions and runs five to seven years, which in nearly every city puts it
over the threshold requiring a **public council vote**. So it surfaces as a
dated council resolution:

> *"Resolution authorizing a five-year agreement with Tyler Technologies for a
> police records management system in an amount not to exceed $2,450,000, with
> two additional one-year renewal options"*

Vendor, term, ceiling, renewals, date — everything the pitch engine needs, and
it appears when the deal is approved rather than in an annual data release.
Legistar exposes this for several hundred cities with no API key.

For the agencies that publish nothing, a records request is the route, which is
why the letter generator is a first-class feature rather than an afterthought.

### Live results

`docs/` holds a real collection run produced by GitHub Actions against the live
public APIs — not a fixture. Latest run: **265 contracts across 190 agencies in
44 states**, 261 with expiration dates, from **96 city council agenda systems**
plus federal awards.

Real RMS / CAD / MDT contracts it found:

| Agency | Incumbent | System | Expires | Annual |
|---|---|---|---|---|
| Denver PD | Versaterm | RMS | 2028-12-22 | $4,110,714 |
| Fresno PD | Axon | CAD | 2029-07-25 | $3,673,653 |
| Long Beach PD | CentralSquare | RMS | 2021-06-16 | $2,452,691 |
| Newark PD | Mark43 | CAD | 2032-12-17 | $1,142,857 |
| San Antonio PD | Mark43 | RMS | 2026-11-14 | $708,311 |
| Corpus Christi PD | Hexagon | CAD | 2026-10-26 | $577,017 |
| Naperville PD | Tyler Technologies | CAD | 2033-09-19 | $527,924 |
| Mesa PD | Hexagon / Versaterm | CAD + RMS | 2031-02-25 | $390,056 |
| Rialto PD | CentralSquare / SOMA | CAD + RMS | 2029-09-24 | $595,571 |

Every row links back to the council item or federal award it came from.

```bash
# Rebuild it; the runner has the network access
gh workflow run collect.yml -f sources="legistar usaspending" -f councils=true
```

**How the council layer got to 96 cities.** There is no directory of which
cities run Legistar and no list of their slugs, so `discover-councils` derives
candidates from 413 cities and counties across 44 states, generates the
predictable slug shapes, and probes all 910 concurrently. Whatever answers
becomes a source. The sweep takes about 75 seconds.

Bare county stems are deliberately not probed: `king`, `orange` and `wayne`
would match whichever unrelated jurisdiction owns that slug, filing one
county's agendas under another's name.

### Prove it reaches real data first

```bash
pdcontracts try
```

No database, no config, no API key. It queries USAspending.gov live and prints
real federal law-enforcement software awards with links you can click through
to verify. If your network or a corporate proxy is blocking the API, this says
so explicitly rather than returning an empty pipeline that looks like "no data
exists".

### Getting real data, start to finish

```bash
pdcontracts init
pdcontracts bootstrap --write     # find, test and pin real datasets
pdcontracts collect               # council agendas + federal awards + portals
pdcontracts serve                 # look at the pipeline
```

`bootstrap` is the step that used to be manual. For every configured city it
searches the Socrata catalog, **probes each candidate dataset with a real
request**, checks whether the column mapper can find a vendor and an expiration
in it and whether it actually contains police rows, then pins the winners into
`config/sources.yml`. Run it without `--write` first to see what it found.

Coverage builds in this order: council agendas and federal awards give you a
real pipeline the first afternoon; big-city portals add contract registers;
the mid-size agencies where most deals live come from records requests you send
in batches.

### Sources worth adding by hand

Not everything has an API. These publish searchable contract data that exports
to CSV, which `pdcontracts import` ingests directly:

- **State comptrollers / transparency portals** — Texas (CPA), Florida (FACTS),
  Ohio, Virginia (eVA), Washington, New York (OpenBook). Statewide contracts
  cover every agency buying through the state vehicle.
- **Cooperative purchasing** — Sourcewell, NASPO ValuePoint, OMNIA, BuyBoard,
  HGACBuy, TIPS. These publish master agreement expirations *and* which
  agencies bought off them.
- **Commercial aggregators** — GovSpend, BidPrime, Deltek. Paid, and they are
  scraping the same public sources, but they save time on the long tail.

---

## Install

```bash
git clone https://github.com/AI-Zick/Contract-Expiration-Finder.git
cd Contract-Expiration-Finder
pip install -e .
```

Python 3.9+. Dependencies are `requests` and `PyYAML`.

## Quick start

```bash
pdcontracts init                                   # create the database
pdcontracts import samples/demo_pipeline.csv       # 61 sample contracts
pdcontracts serve                                  # open the dashboard
```

That opens a web dashboard at `http://127.0.0.1:8000` — the version your sales
team actually uses. Everything below is also available on the command line.

```bash
pdcontracts targets --top 20                       # who to pitch, in order
pdcontracts report --format html -o out/pipeline.html   # shareable single file
```

Output:

```
  #    PRI  AGENCY                            ST  INCUMBENT              EXPIRES     PITCH BY      ANNUAL  STAGE
  1   69.6  Riverside County Sheriff's Office  IL  CentralSquare          2027-09-30  2027-02-01     $896k  Pitch now
  2   69.4  Springfield Police Department      IL  Tyler Technologies     2028-06-30  2027-02-01     $629k  Pitch now
  3   47.4  Lakeview Police Department         IL  CODY Systems           2027-03-31  2026-02-01      $61k  Procurement live
  4   40.1  Riverside County Sheriff's Office  IL  Mark43                 2029-12-31  2029-02-01     $250k  Too early - watch
```

`PITCH BY` is the column that matters. It is not the expiration date — it is the
date the agency's budget request is due for the fiscal year in which the
contract expires. Miss it and you are selling into next cycle.

---

## The dashboard

```bash
pdcontracts serve                    # localhost:8000, rebuilt from the db each request
pdcontracts serve --state TX CA --stage pitch_now
```

**Pitch calendar** is the default view. Each row is one agency; the solid bar is
the window where a pitch can still change the outcome, the thin line runs on to
expiration ◆, and the vertical rule is today. Colour is the stage. Because the
bar ends at the budget deadline rather than the expiration, you can see at a
glance which deals are still winnable and which are already decided.

Gridlines are calendar years, not fiscal years — agencies run different fiscal
calendars, so a shared fiscal grid would be wrong for most rows. Each row marks
its own budget deadline instead.

Click any row for the reasoning: the fiscal year the money comes from, the
category's term and stickiness, renewal options, and every underlying contract.
**Table** view gives sortable columns; **Copy CSV** takes the current filter
into your CRM.

The server binds to `127.0.0.1` by default. A contract pipeline is commercially
sensitive — use `--host 0.0.0.0` only deliberately.

For sharing outside your network, `report --format html -o file.html` writes the
same dashboard as one self-contained file with the data baked in. No server, no
build step, no external assets beyond a webfont.

---

## Collecting real data

### 1. Federal awards (works immediately)

```bash
pdcontracts collect --only usaspending
```

Direct federal law enforcement purchases, plus Byrne/JAG and COPS grants to
cities. Grants are worth as much as contracts here: a city that just took a
grant naming "records management" has appropriated money and **has not chosen a
vendor yet**. That is the earliest signal available anywhere.

### 2. City and state portals

Dataset IDs change and cities retire datasets, so none are hardcoded. Discover
them at runtime:

```bash
pdcontracts discover --all              # sweeps every domain in sources.yml
pdcontracts discover data.cityofchicago.org
```

Paste the dataset id into `config/sources.yml`, set `enabled: true`, then:

```bash
pdcontracts doctor      # confirms each source is reachable and mappable
pdcontracts collect
```

Column names are inferred automatically — `end_date`, `contract_expiration` and
`Term Thru` all resolve to the same field. If a portal maps wrong, pin it:

```yaml
columns: {end_date: contract_expiration, vendor: supplier_name}
```

Set `SOCRATA_APP_TOKEN` (free) to raise rate limits.

### 3. Records requests for everything else

```bash
pdcontracts foia --out letters/ --name "Jane Rep" --org "Acme PD Software" \
                 --email jane@acme.com
```

Generates one letter per agency that has no expiration date on record, citing
the correct state statute. The letters are scoped narrowly on purpose — broad
requests get fee estimates and delays, specific ones get answered. Responses
come back as spreadsheets, which go straight back in:

```bash
pdcontracts import responses/springfield.csv --state IL --source-name foia-2026
```

### 4. Cooperative purchasing vehicles

```bash
pdcontracts collect --only cooperative
pdcontracts vehicles
```

An agency can buy off an existing cooperative master agreement (Sourcewell,
NASPO, OMNIA, BuyBoard) and skip a competitive RFP entirely — turning a
12-month procurement into weeks. `config/cooperative_contracts.csv` ships as a
**template with unverified dates**; fill it in from the co-op contract search
pages before relying on it.

---

## How the timing model works

For a July–June fiscal year, replacing a contract that expires in June 2028
means:

```
Oct 2026   start building the case with the department   <- pitch window opens
Feb 2027   department budget request due to finance      <- PITCH BY
Jun 2027   council adopts the FY2028 budget
Jul 2027   FY2028 begins, money is available
Jun 2028   incumbent contract expires
```

You had to be in the room in late 2026 to win a deal that closes in 2028.

Each opportunity is staged against today:

| Stage | Meaning |
|---|---|
| `pitch_now` | Inside the budget-influence window. Highest leverage. |
| `procurement_live` | Money is allocated; compete on the solicitation instead. |
| `too_early` | Watchlist. The tool tells you the month to start. |
| `late` | Inside 3 months of expiry; incumbent has likely renewed. |
| `expired` | Past expiration with no successor found — usually an extension, and an agency on an extension is unusually reachable. |
| `unknown` | No expiration on record. Send a records request. |

Fiscal calendars are per-agency: most governments start in July, but Chicago
and Seattle run January, DC and most Texas cities October, New York State April.
Getting this wrong moves the pitch date by months, so agency-level overrides
live in `config/agencies_seed.csv`.

### Priority score

Weighted 0–100 across five factors:

| Factor | Weight | Why |
|---|---|---|
| Timing | 40 | A deal being decided now beats a bigger one that is not. |
| Deal size | 25 | Log-scaled annual value. |
| Winnability | 20 | Inverse of incumbent stickiness — ALPR churns, CAD does not. |
| Agency size | 10 | Log-scaled sworn officer count. |
| Data confidence | 5 | Penalizes inferred dates and fuzzy column mappings. |

Timing deliberately outranks winnability: your rep's next call should go to the
agency whose money is being decided this quarter.

### Suite grouping

RMS, CAD and MDT are nearly always bought from one vendor in one procurement.
Showing three rows for one decision triples your apparent pipeline and hides
that a single displacement wins all three, so they are grouped into one
opportunity per agency + incumbent, timed off the **earliest** expiration in the
group — that is the date that forces the decision. Use `--ungrouped` to see
individual contracts.

---

## Command reference

| Command | Purpose |
|---|---|
| `init` | Create the database, load agency reference data |
| `try` | Hit a live public API immediately, no setup |
| `bootstrap [--write]` | Find, probe and pin real datasets automatically |
| `discover [domain] [--all]` | Search a Socrata portal by hand |
| `doctor` | Check every configured source is reachable and mappable |
| `collect [--only X] [--state ST]` | Run the collectors |
| `import FILE` | Load a CSV (records responses, exports, purchased lists) |
| `serve [--port N]` | Open the interactive dashboard in a browser |
| `targets [--detail] [--json]` | Ranked list of who to pitch and when |
| `report --format html\|csv` | Self-contained dashboard, or CSV |
| `foia [--out DIR]` | Generate records request letters |
| `vehicles` | Cooperative purchasing vehicles |
| `stats [--log]` | Coverage and collection history |
| `vendors` / `categories` | The market map and timing model |

Useful filters on `targets` and `report`:
`--state TX CA`, `--stage pitch_now`, `--vendor Tyler`, `--min-value 100000`,
`--all-categories`, `--top 50`, `--today YYYY-MM-DD`.

---

## Vendor taxonomy

95 vendors across 24 categories, with acquisitions mapped to parents — a
Spillman contract is a Motorola relationship, a Zuercher contract is
CentralSquare, a Fusus contract is Axon. This is what turns a generic city
contract register into police-software intelligence.

```bash
pdcontracts vendors --search motorola
pdcontracts categories
```

Classification is vendor-first (reliable) and falls back to description
keywords (less so). It knows Axon sells Tasers as well as software, and that a
Motorola radio contract is infrastructure rather than a software deal.

---

## Accuracy and limits

- **Sworn officer counts in `config/agencies_seed.csv` are approximate**, used
  only to weight agency size in ranking. Refresh from FBI UCR Police Employee
  Data before treating them as facts.
- **Fiscal year months are confirmed for some agencies and inferred for the
  rest.** Verify a city's budget calendar before acting on its dates.
- **Cooperative contract dates ship unverified** and must be filled in.
- **Inferred expirations** (start date + typical term, when a source gives no
  end date) are flagged in the rationale. Confirm before acting.
- **Council-derived expirations are computed**, not quoted: the resolution
  states a term, and the end date is that term added to the approval date. The
  executed contract may start weeks later. Treat these as accurate to the month
  and confirm before acting.
- Everything collected here is public procurement data. Confirm expiration and
  renewal terms with the agency before committing to a plan.

## Development

```bash
pip install -e ".[dev]"
pytest              # 245 tests, no network required
```

Connectors take an injected HTTP fetcher, so the whole suite runs offline
against recorded portal responses.

The dashboard is one HTML asset (`pdcontracts/assets/dashboard.html`) with a
JSON placeholder. `pdcontracts/web.py` injects the payload and either wraps it
in a document shell (server, export) or returns the bare fragment (for hosts
that supply their own). One UI, three surfaces.

Its stage colours were checked with a colourblind-safety validator rather than
chosen by eye: green/amber/blue/crimson clear ΔE 10+ separation under
deuteranopia and protanopia, in both light and dark steps.

### What the live data changed

Running against real records found five defects that no fixture would have:

1. **Transit agencies run computer-aided dispatch too.** Three transit
   districts came back as police-software leads. Federal grants now need a
   police signal in the award text or a law-enforcement funding programme.
2. **"Records management system" is generic enterprise IT.** A $69M Army
   personnel records system, a USDA document archive and an Army fire-service
   system all classified as police RMS. Categories now veto the non-policing
   senses of their own vocabulary.
3. **Legistar rejects `tolower()` inside `substringof`.** Every city silently
   fell back to an unfiltered page and matched nothing. Case variants are now
   matched explicitly, and the collection log records which query path ran.
4. **Amendment chains are one contract, not several.** Denver's fifth, sixth
   and seventh Versaterm agreements each appear as their own council item;
   timing off the earliest pointed at an agreement superseded twice over.
5. **One slow jurisdiction could stall a national run.** Collection had no
   per-source time bound and used a 45-second, three-retry fetcher. Every
   source now runs against a clock and truncates itself rather than the run.
6. **"Public safety" was indexed as a vendor alias.** It normalized out of
   "public safety corporation" and, being the longest match, attributed
   Denver's Versaterm contracts to CentralSquare.

### Adding a source

Subclass `Source` in `pdcontracts/sources/`, implement `collect()` and
`check()`, decorate with `@register`. Return a `SourceResult` with a status
instead of raising — one broken portal must never abort a national run.
