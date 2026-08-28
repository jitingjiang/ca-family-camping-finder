# CA Family Camping Finder

A Streamlit trip planner for **California** camping: federal sites (Recreation.gov), CA State Parks (ReserveCalifornia), and a small curated private / glamping list.

**Use it here:** [ca-family-camping-finder-jtjiang.streamlit.app](https://ca-family-camping-finder-jtjiang.streamlit.app/)

Enter people, dates, origin, camping type, and budget. The app filters a catalog, looks up dates on public campgrounds in those results, and sends you to the **official Book** page. It never logs in or completes a reservation.

The first visit after a quiet stretch may take a minute while the free Streamlit Cloud app wakes up.

## Run it on your computer

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
./run_dashboard.sh
```

Opens [http://localhost:8502](http://localhost:8502).

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

Live check waits ~1 second between requests and caps at 80 public campgrounds per search. If an endpoint is blocked or flaky, rows still appear with a **Book** button.

We do **not** snipe cancellations, log in, or place reservations.

## Honest limits

- **Distance** is map (straight-line) miles. **Drive time** is an estimate from that (roads wind; no live traffic).
- Public-land nightly prices are often estimates. Confirm on the booking page.
- Reservation windows (usually ~6 months rolling) matter more than this app. Popular sites vanish in minutes.
- Yosemite and some parks add lotteries or timed entry on top of a campsite.
- This is a personal planner, not Recreation.gov, ReserveCalifornia, or Hipcamp.

## Data sources

- [Recreation.gov](https://www.recreation.gov/) campground search + availability JSON
- [RIDB](https://ridb.recreation.gov/) (optional, official federal metadata)
- [ReserveCalifornia](https://www.reservecalifornia.com/) park/facility list + availability grid
- [CNRA State Parks campgrounds](https://data.cnra.ca.gov/dataset/campgrounds) GIS
- Hand-curated private / glamping list in `data/private_glamping.json`
