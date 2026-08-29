# CA Family Camping Finder

A Streamlit trip planner for **California** camping: federal sites (Recreation.gov), CA State Parks (ReserveCalifornia), and a small curated private / glamping list.

**Use it here:** [ca-family-camping-finder-jtjiang.streamlit.app](https://ca-family-camping-finder-jtjiang.streamlit.app/)

Enter people, dates, origin, camping type, and budget. The app filters a catalog, looks up dates on public campgrounds in those results, and sends you to the **official Book** page. It never logs in or completes a reservation.

**Note:** The campground **list** is a snapshot in this repo (refresh with `ingest.py` a couple of times a year). **Availability** is fetched live on each search.

## Data sources

- [Recreation.gov](https://www.recreation.gov/) campground search + availability JSON
- [RIDB](https://ridb.recreation.gov/) (optional, official federal metadata)
- [ReserveCalifornia](https://www.reservecalifornia.com/) park/facility list + availability grid
- [CNRA State Parks campgrounds](https://data.cnra.ca.gov/dataset/campgrounds) GIS
- Hand-curated private / glamping list in `data/private_glamping.json`
