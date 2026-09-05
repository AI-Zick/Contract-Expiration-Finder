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

| Where contracts live | Coverage | This tool |
|---|---|---|
| Federal awards (USAspending.gov) | Federal LE agencies + DOJ grants to cities | Automated, no API key |
| City open-data portals (Socrata) | A few hundred large cities | Automated, needs dataset discovery |
| State procurement portals | Varies wildly by state | Partly automated (Socrata states) |
| Cooperative purchasing vehicles | Thousands of agencies buy off these | Maintained CSV |
| **Everything else** | **The large majority of agencies** | **Records requests** |

That last row is the honest part. For most agencies the only way to get a
contract expiration date is to ask for it, so this tool generates the request
letters as a first-class feature rather than pretending the gap does not exist.

Expect to build coverage in this order: federal awards and big-city portals get
you a starting pipeline in an afternoon; the mid-size agencies where most deals
actually live come from records requests you send in batches.

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
| `discover [domain] [--all]` | Find contract datasets on Socrata portals |
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
- Everything collected here is public procurement data. Confirm expiration and
  renewal terms with the agency before committing to a plan.

## Development

```bash
pip install -e ".[dev]"
pytest              # 159 tests, no network required
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

### Adding a source

Subclass `Source` in `pdcontracts/sources/`, implement `collect()` and
`check()`, decorate with `@register`. Return a `SourceResult` with a status
instead of raising — one broken portal must never abort a national run.
