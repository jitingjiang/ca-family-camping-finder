# CA Family Camping Finder

A Streamlit trip planner for **California** camping: federal sites (Recreation.gov), CA State Parks (ReserveCalifornia), and a small curated private / glamping list.

**Use it here:** [ca-family-camping-finder-jtjiang.streamlit.app](https://ca-family-camping-finder-jtjiang.streamlit.app/)

Enter people, dates, origin, camping type, and budget. The app filters a catalog, looks up dates on public campgrounds in those results, and sends you to the **official Book** page. It never logs in or completes a reservation.

The first visit after a quiet stretch may take a minute while the free Streamlit Cloud app wakes up.

## Versions

| Branch / tag | What it is | Where it runs |
|---|---|---|
| `main` | The stable version. This is the link to share. | [ca-family-camping-finder-jtjiang.streamlit.app](https://ca-family-camping-finder-jtjiang.streamlit.app/) |
| `v2` | Work in progress, merged into `main` when it's ready. | A second Streamlit Cloud app deployed from this branch |
| `v1.0` (tag) | Frozen marker for the first working version. | — |

Each Streamlit Cloud app watches one branch, so pushing to `v2` rebuilds only the
staging app and never touches the live one. To release:

```bash
git checkout main && git merge v2 && git push
```

## Run it on your computer

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
./run_dashboard.sh
```

Opens [http://localhost:8502](http://localhost:8502).

Use the project `.venv` for tests too — plain `python -m pytest` often hits conda and misses `pydeck`:

```bash
./run_tests.sh
```

## Refresh the catalog vs search

| Script | When to run it | What it does |
|---|---|---|
| [`ingest.py`](ingest.py) | When you want a fresh campground list | Pulls Recreation.gov campgrounds in CA, optional [RIDB](https://ridb.recreation.gov/profile) federal metadata, ReserveCalifornia parks/facilities, CNRA State Parks GIS, and [`data/private_glamping.json`](data/private_glamping.json). Writes [`data/campgrounds.json`](data/campgrounds.json). |
| [`dashboard.py`](dashboard.py) | Whenever you want to plan a trip | Form + map + cards. Reads the catalog. Live availability is on-demand for public campgrounds in your filtered results (closest first, capped at 80). |

```bash
.venv/bin/python ingest.py
./run_dashboard.sh
```

A snapshot of `data/campgrounds.json` ships in the repo so the dashboard works before you ingest again.

## Estimates never hide a campground

About half the catalog's nightly prices, and most of its party limits, are house
estimates rather than real numbers from the booking system. Those estimates **rank**
a result, they never remove it: a place we can't confirm still shows up, sorted
below the confirmed matches and flagged on its card. Only a *confirmed* price or
party limit that misses your search is filtered out.

Records carry `price_known` and `capacity_known` so the app can tell the two apart.
`capacity_known` is written by `ingest.py` — until you re-run the ingest, every
party limit is treated as an estimate.

## Tests

```bash
./run_tests.sh
```

Covers the filtering and ranking rules against the shipped catalog. No network,
runs in about a second.

`run_tests.sh` finds the project venv the same way `run_dashboard.sh` does, then
installs [`requirements-dev.txt`](requirements-dev.txt) into it. Use it rather than a
bare `python -m pytest`: a bare `python` can resolve to conda or the system install,
neither of which has this app's dependencies — the tests import `dashboard`, so
`streamlit` and `pydeck` must be present even though the functions under test are pure.

## Optional RIDB key

Federal **catalog** data already comes from Recreation.gov search (no key). To also merge the official Recreation Information Database:

1. Get a free key at [ridb.recreation.gov/profile](https://ridb.recreation.gov/profile)
2. Put `RIDB_API_KEY=your_key` in `.env`
3. Re-run `ingest.py`

Do not commit `.env`.

## What live availability covers

- **Recreation.gov** (national parks, national forests, BLM, etc.): read-only month availability.
- **ReserveCalifornia** (CA State Parks): read-only unit grid.
- **Private / glamping**: catalog only. Open their website for dates.

Live check waits ~1 second between requests and caps at 80 public campgrounds per search. A one-off failure is tolerated and reported as such; only a run of consecutive failures — an outage or a block — stops the remaining lookups. Either way rows still appear with a **Book** button.

We do **not** snipe cancellations, log in, or place reservations.

## Honest limits

- **Distance** is map (straight-line) miles. **Drive time** is an estimate from that (roads wind; no live traffic).
- About half the nightly prices, and most party limits, are estimates rather than real numbers — see [Estimates never hide a campground](#estimates-never-hide-a-campground). Confirm on the booking page.
- Reservation windows (usually ~6 months rolling) matter more than this app. Popular sites vanish in minutes.
- Yosemite and some parks add lotteries or timed entry on top of a campsite.
- This is a personal planner, not Recreation.gov, ReserveCalifornia, or Hipcamp.

## Data sources

- [Recreation.gov](https://www.recreation.gov/) campground search + availability JSON
- [RIDB](https://ridb.recreation.gov/) (optional, official federal metadata)
- [ReserveCalifornia](https://www.reservecalifornia.com/) park/facility list + availability grid
- [CNRA State Parks campgrounds](https://data.cnra.ca.gov/dataset/campgrounds) GIS
- Hand-curated private / glamping list in `data/private_glamping.json`
