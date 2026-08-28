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

## Data sources

- [Recreation.gov](https://www.recreation.gov/) campground search + availability JSON
- [RIDB](https://ridb.recreation.gov/) (optional, official federal metadata)
- [ReserveCalifornia](https://www.reservecalifornia.com/) park/facility list + availability grid
- [CNRA State Parks campgrounds](https://data.cnra.ca.gov/dataset/campgrounds) GIS
- Hand-curated private / glamping list in `data/private_glamping.json`
