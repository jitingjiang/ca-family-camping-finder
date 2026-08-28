"""Streamlit trip planner for California family camping."""

from __future__ import annotations

import json
import math
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pydeck as pdk
import streamlit as st

from availability import MAX_LIVE_CHECKS, check_shortlist
from cities import CITIES, geocode_ca_city, lookup_city
from normalize import AGENCY_LABELS, BOOKING_LABELS, CAMP_TYPES

ROOT = Path(__file__).resolve().parent
CAMPGROUNDS_JSON = ROOT / "data" / "campgrounds.json"
ASSETS_DIR = ROOT / "assets"
CITY_NAMES = list(CITIES.keys())
# Roads aren't a straight line; mixed highway / two-lane, no live traffic.
ROAD_FACTOR = 1.32
AVG_MPH = 46.0

DATE_MODE_SKIP = "Don't check — just show the list (fastest)"
DATE_MODE_CHECK = "Check whether my nights are free (slower)"

# Status values worth colouring in the card's metric row. Everything else stays
# plain so the four cells read as one consistent row.
STATUS_COLOR = {"available": "green", "first_come": "green", "full": "red"}

STATUS_RANK = {
    "available": 0,
    "first_come": 1,
    "check_site": 2,
    "not_yet_released": 3,
    "lottery": 4,
    "unknown": 5,
    "full": 6,
}

st.set_page_config(
    page_title="CA Family Camping Finder",
    layout="wide",
    menu_items={
        "Get Help": None,
        "Report a bug": None,
        "About": (
            "A personal California camping planner. It searches a catalog of public "
            "and private campgrounds and sends you to the official booking site. "
            "It never logs in, takes payment, or holds a reservation for you."
        ),
    },
)


CAMP_TYPE_GUIDE = [
    (
        "tent",
        "Tent",
        "You bring the tent. A table and fire ring are usually at the site.",
    ),
    (
        "drive_in",
        "Drive-in / auto",
        "You park at the site. This is the usual family campground.",
    ),
    (
        "rv_hookups",
        "RV hookups",
        "A pad for a trailer or motorhome, with water or power at the site.",
    ),
    (
        "cabin_glamping",
        "Cabin / yurt / glamping",
        "A small building with beds. Easiest if you don’t own camping gear.",
    ),
    (
        "group",
        "Group",
        "A big site for many people. Skip this for one family.",
    ),
    (
        "walk_in",
        "Walk-in / hike-in",
        "Park in a lot and carry your gear. Harder with kids on a first trip.",
    ),
]


def render_type_guide() -> None:
    for start in range(0, len(CAMP_TYPE_GUIDE), 3):
        cols = st.columns(3)
        for col, (key, title, blurb) in zip(cols, CAMP_TYPE_GUIDE[start : start + 3]):
            path = ASSETS_DIR / f"type_{key}.png"
            with col:
                if path.exists():
                    st.image(str(path), width="stretch")
                st.markdown(f"**{title}**")
                st.caption(blurb)


def haversine_miles(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 3958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(min(1.0, a)))


def format_drive(minutes: int) -> str:
    minutes = max(5, int(minutes))
    if minutes < 60:
        return f"~{minutes} min"
    hours, mins = divmod(minutes, 60)
    if mins == 0:
        return f"~{hours} hr"
    return f"~{hours} hr {mins} min"


def estimate_drive(miles: float) -> tuple[int, str]:
    minutes = int(round((miles * ROAD_FACTOR / AVG_MPH) * 60))
    return minutes, format_drive(minutes)


def resolve_origin(
    selected: str, typed: str, lat: float, lng: float
) -> tuple[str, tuple[float, float], str | None]:
    """Return (label, coords, warning). Custom coordinates win, then typed city, then dropdown."""
    if lat and lng:
        return f"Custom pin ({lat:.3f}, {lng:.3f})", (float(lat), float(lng)), None
    typed = (typed or "").strip()
    if typed:
        hit = lookup_city(typed)
        if hit:
            return hit[0], hit[1], None
        geo = geocode_ca_city(typed)
        if geo:
            return geo[0], geo[1], None
        return (
            selected,
            CITIES[selected],
            f"Could not find “{typed}” in California. Using {selected} instead. "
            "Pick a city from the list or enter latitude/longitude.",
        )
    return selected, CITIES[selected], None


@st.cache_data(show_spinner=False)
def load_catalog() -> dict[str, Any]:
    if not CAMPGROUNDS_JSON.exists():
        return {}
    return json.loads(CAMPGROUNDS_JSON.read_text(encoding="utf-8"))


def price_in_range(rec: dict[str, Any], price_min: int, price_max: int) -> bool:
    """Does this record's nightly range overlap the budget? Unknown prices count as a miss."""
    lo, hi = rec.get("price_min"), rec.get("price_max")
    if lo is None or hi is None:
        return False
    return not (hi < price_min or lo > price_max)


def soft_flags(rec: dict[str, Any], *, people: int, price_min: int, price_max: int) -> list[str]:
    """Reasons this row might not fit, based on data we guessed rather than confirmed.

    These never remove a row — they rank it lower and get shown on the card, because
    most of the catalog's prices and party limits are house estimates, and silently
    dropping a real campground on an estimate is worse than showing it with a caveat.
    """
    flags: list[str] = []
    if not rec.get("price_known") and not price_in_range(rec, price_min, price_max):
        flags.append("Price is our estimate and looks outside your budget")
    capacity = rec.get("max_people")
    if not rec.get("capacity_known") and capacity and int(capacity) < people:
        flags.append(f"Party limit not confirmed (we assume {int(capacity)})")
    return flags


def type_labels(types: list[str]) -> str:
    return ", ".join(CAMP_TYPES.get(t, t) for t in types) or "—"


def amenity_labels(items: list[str]) -> str:
    pretty = {
        "showers": "Showers",
        "flush_toilets": "Flush toilets",
        "restrooms": "Restrooms",
        "water": "Water",
        "hookups": "Hookups",
        "dump_station": "Dump station",
        "store": "Store",
        "accessible": "Accessible",
        "wifi": "Wi-Fi",
        "pool": "Pool",
        "restaurant": "Restaurant",
    }
    return ", ".join(pretty.get(a, a) for a in items) if items else "See booking page"


def pets_label(value: Any) -> str:
    if value is True:
        return "Pets allowed — check their rules"
    if value is False:
        return "No pets"
    return "Pets: check the listing"


def listing_link(rec: dict[str, Any]) -> tuple[str | None, str | None]:
    """Return (url, search_hint). State parks open the ReserveCalifornia home page."""
    if rec.get("booking_system") == "reservecalifornia":
        hint = rec.get("parent_name") or rec.get("name")
        return "https://www.reservecalifornia.com/", hint
    url = rec.get("booking_url") or rec.get("website")
    return (url or None), None


def stay_label(check_in: date, check_out: date) -> str:
    if check_in.year == check_out.year and check_in.month == check_out.month:
        return f"{check_in:%b} {check_in.day}–{check_out.day}, {check_out:%Y}"
    if check_in.year == check_out.year:
        return f"{check_in:%b} {check_in.day}–{check_out:%b} {check_out.day}, {check_out:%Y}"
    return f"{check_in:%b} {check_in.day}, {check_in:%Y}–{check_out:%b} {check_out.day}, {check_out:%Y}"


def avail_counts(results: list[dict[str, Any]]) -> dict[str, int]:
    counts = {
        "available": 0,
        "first_come": 0,
        "full": 0,
        "not_yet_released": 0,
        "checked": 0,
        "unchecked": 0,
    }
    for rec in results:
        avail = rec.get("availability") or {}
        status = avail.get("status") or "unknown"
        if avail.get("checked"):
            counts["checked"] += 1
        else:
            counts["unchecked"] += 1
        if status in counts:
            counts[status] += 1
    return counts


def map_selected_cg_id(event: Any) -> str | None:
    if event is None:
        return None
    selection = (
        event["selection"]
        if isinstance(event, dict)
        else getattr(event, "selection", None)
    )
    if selection is None:
        return None
    objects = (
        selection["objects"]
        if isinstance(selection, dict)
        else getattr(selection, "objects", None)
    ) or {}
    pins = objects.get("campgrounds") or []
    if not pins:
        return None
    cid = pins[0].get("cg_id")
    return str(cid) if cid else None


def avail_display(avail: dict[str, Any] | None) -> tuple[str, str | None]:
    avail = avail or {}
    status = avail.get("status") or "unknown"
    n = avail.get("sites_available")
    if status == "available":
        if n:
            return "Available", f"{n} site(s) open for your whole stay."
        return "Available", "Open for your whole stay."
    if status == "full":
        return "Not open these nights", "No site is free for every night. Try other dates on Book."
    if status == "first_come":
        return "Walk-up", "First-come — no online hold. Arrive early."
    if status == "not_yet_released":
        return "Dates not released yet", "These nights are not in the booking window yet."
    if status == "lottery":
        return "Lottery", "This one uses a drawing. Check the listing for rules."
    if status == "check_site":
        return "See their website", "Private listing — dates are on their website, not here."
    return "Check dates on Book", None


def miles_for_drive_minutes(minutes: int) -> float:
    return (minutes / 60.0) * AVG_MPH / ROAD_FACTOR


def filter_catalog(
    campgrounds: list[dict[str, Any]],
    *,
    origin: tuple[float, float],
    max_miles: float | None,
    people: int,
    price_min: int,
    price_max: int,
    confirmed_price_only: bool,
    types: list[str],
    agencies: list[str],
) -> list[dict[str, Any]]:
    """Filter the catalog.

    Hard filters are the things the user chose (agency, camp type, distance) and
    the things we actually know (a confirmed price, a confirmed party limit).
    Guessed values only ever set a soft flag — see soft_flags().
    """
    lat0, lng0 = origin
    rows: list[dict[str, Any]] = []
    for rec in campgrounds:
        lat, lng = rec.get("lat"), rec.get("lng")
        if lat is None or lng is None:
            continue
        if rec.get("agency") not in agencies:
            continue
        rec_types = rec.get("camp_types") or []
        if types and not any(t in rec_types for t in types):
            continue
        if confirmed_price_only and not rec.get("price_known"):
            continue
        max_people = rec.get("max_people")
        if rec.get("capacity_known") and max_people and int(max_people) < people:
            continue
        if rec.get("price_known") and not price_in_range(rec, price_min, price_max):
            continue
        miles = haversine_miles(lat0, lng0, float(lat), float(lng))
        if max_miles is not None and miles > max_miles:
            continue
        drive_min, drive_label = estimate_drive(miles)
        row = dict(rec)
        row["distance_mi"] = round(miles, 1)
        row["drive_min"] = drive_min
        row["drive_label"] = drive_label
        row["soft_flags"] = soft_flags(
            rec, people=people, price_min=price_min, price_max=price_max
        )
        rows.append(row)
    rows.sort(key=lambda r: (r["distance_mi"], r.get("price_min") or 9999))
    return rows


def rank_results(
    rows: list[dict[str, Any]], sort_by: str = "closest"
) -> list[dict[str, Any]]:
    def key(row: dict[str, Any]) -> tuple:
        distance = row.get("distance_mi") or 9999
        price = row.get("price_min") or 9999
        # Rows we only kept on an estimate sink below the ones that actually fit.
        soft = 1 if row.get("soft_flags") else 0
        if sort_by == "available":
            status = (row.get("availability") or {}).get("status") or "unknown"
            return (soft, STATUS_RANK.get(status, 9), distance, price)
        return (soft, distance, price)

    return sorted(rows, key=key)


def render_card(rec: dict[str, Any], *, from_map: bool = False) -> None:
    avail = rec.get("availability") or {}
    with st.container(border=True):
        if from_map:
            st.caption("From the map — this is the pin you clicked.")
        top, action = st.columns([4, 1])
        with top:
            st.markdown(f"**{rec.get('name')}**")
            parent = rec.get("parent_name") or rec.get("city") or ""
            bits = [
                f"{rec.get('distance_mi')} mi",
                f"{rec.get('drive_label')} drive (est.)" if rec.get("drive_label") else "",
                AGENCY_LABELS.get(rec.get("agency") or "", rec.get("agency_name") or ""),
            ]
            if parent:
                bits.insert(1, parent)
            st.caption(" · ".join(str(b) for b in bits if b))
        with action:
            url, search_hint = listing_link(rec)
            if url:
                st.link_button("Book", url, width="stretch")
        # All four cells use the same call and weight so the row reads as one
        # thing; only the status carries colour, since that is the live signal.
        m1, m2, m3, m4 = st.columns(4)
        label, detail = avail_display(avail)
        color = STATUS_COLOR.get((avail.get("status") or "unknown"))
        m1.write(f":{color}[{label}]" if color else label)
        price_lo, price_hi = rec.get("price_min"), rec.get("price_max")
        if price_lo is not None:
            suffix = "" if rec.get("price_known") else " est."
            m2.write(f"${price_lo}–${price_hi}/night{suffix}")
        else:
            m2.write("Price on booking page")
        m3.write(type_labels(rec.get("camp_types") or []))
        m4.write(BOOKING_LABELS.get(rec.get("booking_system") or "", ""))
        if search_hint:
            st.caption(f"On the booking site, search for **{search_hint}**.")
        if detail:
            st.caption(detail)
        for flag in rec.get("soft_flags") or []:
            st.caption(f":orange[Heads up — {flag}. Confirm on the booking page.]")
        with st.expander("Specs and how to book"):
            capacity = rec.get("max_people")
            capacity_text = (
                f"up to {capacity}" if capacity else "—"
            ) + ("" if rec.get("capacity_known") else " (our estimate)")
            st.write(f"**Party:** {capacity_text} · **{pets_label(rec.get('pets'))}**")
            st.write(f"**Amenities:** {amenity_labels(rec.get('amenities') or [])}")
            if rec.get("first_come"):
                st.write("**Reservable:** first-come / walk-up (no online hold).")
            elif rec.get("reservable"):
                st.write("**Reservable:** yes, on the official site.")
            if rec.get("rating"):
                st.write(
                    f"**Reviews:** {rec.get('rating'):.1f} from {rec.get('review_count') or 0} ratings"
                )
            if rec.get("description"):
                st.write(rec["description"][:500])
            if rec.get("notes"):
                st.info(rec["notes"])
            book, search_hint = listing_link(rec)
            site = rec.get("website") or ""
            if rec.get("booking_system") == "reservecalifornia" and search_hint:
                st.markdown(
                    f"**Reserve:** [Open ReserveCalifornia]({book}) — search for **{search_hint}**."
                )
            elif book:
                st.markdown(f"**Reserve:** [Open listing]({book})")
            if (
                site
                and site.rstrip("/") not in { (book or "").rstrip("/"), "https://www.reservecalifornia.com" }
                and rec.get("booking_system") != "reservecalifornia"
            ):
                st.markdown(f"**Park / property website:** [{site}]({site})")
            steps = [
                "Open **Book** (we never complete a reservation for you).",
                "Confirm dates, site type, and party size on the official page.",
                "Fees and fire rules can change — trust the booking site.",
            ]
            if rec.get("booking_system") == "reservecalifornia":
                steps.insert(
                    1,
                    f"Search for **{search_hint or rec.get('name')}**, then pick your dates.",
                )
            # The card already says private dates live on their website — don't repeat it here.
            st.markdown("\n".join(f"{i}. {s}" for i, s in enumerate(steps, 1)))


def on_map_select() -> None:
    nonce = st.session_state.get("map_nonce", 0)
    cid = map_selected_cg_id(st.session_state.get(f"camp_map_{nonce}"))
    if cid:
        st.session_state["selected_cg_id"] = cid


def render_map(
    results: list[dict[str, Any]],
    origin: tuple[float, float] | None,
    origin_label: str,
    selected_id: str | None = None,
) -> str | None:
    rows = [
        {
            "lat": float(r["lat"]),
            "lon": float(r["lng"]),
            "name": r.get("name") or "Campground",
            "parent": r.get("parent_name") or r.get("city") or "",
            "distance": f"{r.get('distance_mi')} mi",
            "drive": f"{r.get('drive_label')} drive (est.)",
            "cg_id": str(r.get("id") or ""),
            "color": (
                [20, 130, 70, 230]
                if selected_id and r.get("id") == selected_id
                else [200, 30, 0, 180]
            ),
        }
        for r in results
        if r.get("lat") is not None and r.get("lng") is not None
    ]
    if not rows:
        return None
    lat0 = sum(r["lat"] for r in rows) / len(rows)
    lon0 = sum(r["lon"] for r in rows) / len(rows)
    layers = [
        pdk.Layer(
            "ScatterplotLayer",
            data=rows,
            id="campgrounds",
            get_position="[lon, lat]",
            get_radius=900,
            radius_min_pixels=6,
            radius_max_pixels=14,
            get_fill_color="color",
            pickable=True,
            auto_highlight=True,
        )
    ]
    if origin:
        layers.append(
            pdk.Layer(
                "ScatterplotLayer",
                data=[
                    {
                        "lat": origin[0],
                        "lon": origin[1],
                        "name": origin_label,
                        "parent": "Starting point",
                        "distance": "",
                        "drive": "",
                        "cg_id": "",
                        "color": [30, 90, 200, 200],
                    }
                ],
                id="origin",
                get_position="[lon, lat]",
                get_radius=1100,
                radius_min_pixels=7,
                radius_max_pixels=16,
                get_fill_color="color",
                pickable=False,
            )
        )
    deck = pdk.Deck(
        map_style=None,
        initial_view_state=pdk.ViewState(
            latitude=lat0, longitude=lon0, zoom=7, pitch=0
        ),
        layers=layers,
        tooltip={
            "html": "<b>{name}</b><br/>{parent}<br/>{distance} {drive}<br/>Click to open this card",
            "style": {"backgroundColor": "#111", "color": "white", "fontSize": "12px"},
        },
    )
    event = st.pydeck_chart(
        deck,
        width="stretch",
        on_select=on_map_select,
        selection_mode="single-object",
        key=f"camp_map_{st.session_state.get('map_nonce', 0)}",
    )
    st.caption(
        "Red pins are matching campgrounds — click one to jump to its card below. "
        "Green is the pin you clicked. Blue is where you leave from."
    )
    return map_selected_cg_id(event)


def main() -> None:
    payload = load_catalog()
    campgrounds = payload.get("campgrounds") or []
    st.title("CA Family Camping Finder")
    st.caption(
        "Find a California campsite for your family, then reserve on the official site. "
        "This app does not take payment or hold a spot."
    )

    if not campgrounds:
        st.error("No campground list loaded. Refresh the catalog, then reload this page.")
        return

    generated = payload.get("generated_at") or "unknown"
    by_agency = payload.get("by_agency") or {}
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Campgrounds", f"{payload.get('campground_count', len(campgrounds)):,}")
    k2.metric("Federal", f"{by_agency.get('federal', 0):,}")
    k3.metric("State parks", f"{by_agency.get('ca_state_parks', 0):,}")
    k4.metric("Private / glamping", f"{by_agency.get('private', 0):,}")
    st.caption(
        f"Campground list last updated {generated[:10]}. "
        "Prices and party limits marked *est.* are our guesses — the booking site is the truth."
    )

    with st.expander("New to camping? Start here", icon=":material/camping:"):
        st.markdown(
            """
**A first family trip** is usually: drive to a site, park next to it, sleep in a
tent *or* a small cabin, share a restroom with the campground, cook at a picnic
table. It is not a hotel — bring layers, a light, and food. Leave **Tent**,
**Drive-in / auto**, and **Cabin / yurt / glamping** checked below if you’re unsure.

**Camping types** (what the filter means)

- **Tent** — You bring a tent. The site is a dirt or gravel pad with a table and
  usually a fire ring. Bathrooms are down the loop (flush or vault). Fine with kids
  if you can set up in daylight.
- **Drive-in / auto** — You park *at* the site. This is the normal family
  campground. It often overlaps with tent: same place, you just aren’t hiking gear in.
- **RV hookups** — A pad for a trailer or motorhome, sometimes with water / power /
  sewer. Skip this unless you have (or are renting) an RV. A minivan + tent is
  still “drive-in,” not RV hookups.
- **Cabin / yurt / glamping** — A real structure with beds. Easiest first night if
  you don’t own camping gear. Costs more; still confirm heat, bathroom, and linens
  on the booking page (some cabins are bare-bones).
- **Group** — Huge sites for 20+ people (reunions, troops). Too big for most
  families; leave it off unless that’s your trip.
- **Walk-in / hike-in** — Park in a lot and carry everything. Quieter, but hard
  with little kids, a lot of stuff, or a first outing.

One campground can be more than one type (tent + drive-in is very common).
Prefer pictures? Open **Camping types in pictures** just below.

**Where to stay**

- **Federal** — National parks, national forests, some BLM land. Book on
  Recreation.gov. More “out there”; showers are not guaranteed.
- **CA State Parks** — Beaches, redwoods, lakes. Book on ReserveCalifornia.
  Often nicer bathrooms and very popular (coastal weekends vanish fast).
- **Private** — KOAs, ranches, glamping. Book their website. Sometimes a pool or
  store. This app **cannot** see if their nights are open.

**Reservable vs walk-up.** Most popular California sites must be reserved online.
Walk-up / first-come means no hold — you drive in and hope a site is empty
(arrive early). Yosemite and a few famous parks may also use lotteries.

**Packing, very roughly.** Sleeping bags rated for a cold night, extra blanket,
headlamp, water, food you can cook simply, chairs, and a reservation screenshot.
Check [CAL FIRE](https://www.fire.ca.gov/) for fire restrictions before you plan
on a campfire.
            """
        )

    with st.expander("Camping types in pictures", icon=":material/image:"):
        st.caption("Same six types as the filter. One campground can be more than one type.")
        render_type_guide()

    with st.expander("How booking works", icon=":material/event:"):
        st.markdown(
            """
- **Book early.** Recreation.gov and ReserveCalifornia usually open dates on a
  rolling **~6-month** window. Yosemite and coastal state parks often sell out
  in minutes. Create the official account (and save a payment method) *before*
  the drop.
- Midweek and May / September are much easier than July weekends.
- **Distance** is map (straight-line) miles. **Drive time** is an estimate from
  that (roads wind, no live traffic).
- Public-land prices are estimates. Trust the booking page.
- Private / glamping: dates are on *their* website. Also try
  [Hipcamp](https://www.hipcamp.com/) for extra private land.
            """
        )

    today = date.today()
    st.subheader("Your trip")
    max_miles = st.slider(
        "How far are you willing to go?",
        min_value=25,
        max_value=400,
        value=150,
        step=5,
        help="One cutoff: map miles and estimated drive move together. Not live traffic.",
    )
    drive_slider_label = estimate_drive(float(max_miles))[1]
    st.caption(
        f"**{max_miles} miles** ≈ **{drive_slider_label} drive** (estimate, no traffic). "
        "Each campground shows both numbers. This is one filter, not two."
    )
    with st.form("trip"):
        c1, c2, c3 = st.columns(3)
        city = c1.selectbox(
            "Leaving from",
            CITY_NAMES,
            index=CITY_NAMES.index("San Francisco"),
            help="Type to search the list (Fremont, Hayward, San Jose, …).",
        )
        check_in = c2.date_input("Check-in", today + timedelta(days=21))
        check_out = c3.date_input("Check-out", today + timedelta(days=23))
        typed_city = st.text_input(
            "City not in the list? Type it here",
            placeholder="e.g. Los Gatos",
        )
        with st.expander("Or enter coordinates"):
            cc1, cc2 = st.columns(2)
            custom_lat = cc1.number_input(
                "Latitude", value=0.0, format="%.4f", help="Leave 0 to ignore."
            )
            custom_lng = cc2.number_input(
                "Longitude", value=0.0, format="%.4f", help="Leave 0 to ignore."
            )
        c4, c5 = st.columns(2)
        people = c4.number_input("People", min_value=1, max_value=40, value=4)
        price = c5.slider("Nightly budget ($)", 0, 800, (0, 250))
        confirmed_price_only = st.checkbox(
            "Only show places with a confirmed price",
            value=False,
            help=(
                "Most state-park and some federal prices are our estimates, not real rates. "
                "Tick this to see only the ones where the booking system gave us a real price."
            ),
        )
        sort_by = st.radio(
            "List order",
            ["Closest", "Open sites first"],
            horizontal=True,
            help=(
                "Closest is nearest first (miles and estimated drive use the same order). "
                "Open sites first puts bookable spots at the top even if they are farther."
            ),
            key="sort_by",
        )
        types = st.multiselect(
            "Camping type",
            options=list(CAMP_TYPES.keys()),
            default=["tent", "drive_in", "cabin_glamping"],
            format_func=lambda k: CAMP_TYPES[k],
            help=(
                "Tent + drive-in is a normal family campground (park at the site, sleep in a tent). "
                "Cabin/glamping is a bed in a structure. RV hookups are for trailers. "
                "Walk-in means you carry gear from a parking lot. See “New to camping?” above."
            ),
        )
        st.caption(
            "Not sure? Keep **Tent**, **Drive-in / auto**, and **Cabin / yurt / glamping**. "
            "Open **New to camping? Start here** for the differences, or "
            "**Camping types in pictures** if you prefer photos."
        )
        agencies = st.multiselect(
            "Where to stay",
            options=list(AGENCY_LABELS.keys()),
            default=list(AGENCY_LABELS.keys()),
            format_func=lambda k: AGENCY_LABELS[k],
            help=(
                "Federal = Recreation.gov (national parks/forests). "
                "CA State Parks = ReserveCalifornia. "
                "Private = their own website; we can’t see if nights are open."
            ),
        )
        date_mode = st.radio(
            "Checking your nights",
            [DATE_MODE_SKIP, DATE_MODE_CHECK],
            index=1,
            help=(
                "Checking asks the official booking sites whether your nights are free at "
                "each public campground in your results, and labels every card. Nothing is "
                "removed from the list. Private stays are not in those systems. A long list "
                f"takes about a minute (max {MAX_LIVE_CHECKS} lookups)."
            ),
        )
        submitted = st.form_submit_button("Find campgrounds", type="primary")

    if hasattr(check_in, "date") and not isinstance(check_in, date):
        check_in = check_in.date()
    if hasattr(check_out, "date") and not isinstance(check_out, date):
        check_out = check_out.date()

    if submitted:
        if check_out <= check_in:
            st.warning("Check-out must be after check-in.")
            return
        if not agencies:
            st.warning("Pick at least one agency (federal, state parks, or private).")
            return
        origin_label, origin, origin_warning = resolve_origin(
            city, typed_city, float(custom_lat), float(custom_lng)
        )
        if origin_warning:
            st.warning(origin_warning)
        live = date_mode != DATE_MODE_SKIP
        miles_limit = float(max_miles)
        sort_key = "available" if sort_by == "Open sites first" else "closest"
        matches = filter_catalog(
            campgrounds,
            origin=origin,
            max_miles=miles_limit,
            people=int(people),
            price_min=int(price[0]),
            price_max=int(price[1]),
            confirmed_price_only=confirmed_price_only,
            types=types,
            agencies=agencies,
        )
        if live and matches:
            progress = st.progress(0.0, text="Looking up dates…")
            try:
                matches = check_shortlist(
                    matches, check_in, check_out, progress=progress
                )
            except Exception:
                st.info(
                    "We couldn’t look up dates this time. "
                    "The places below still fit your trip — open **Book** to check nights."
                )
                progress.empty()
        st.session_state["results"] = rank_results(matches, sort_by=sort_key)
        _, drive_cut = estimate_drive(float(max_miles))
        range_label = (
            f"within {int(max_miles)} miles ({drive_cut} drive) of {origin_label}"
        )
        st.session_state["search_meta"] = {
            "city": origin_label,
            "range_label": range_label,
            "live": live,
            "count": len(matches),
            "sort_by": sort_key,
            "origin": origin,
            "stay": stay_label(check_in, check_out),
        }
        st.session_state.pop("selected_cg_id", None)
        st.session_state["map_nonce"] = st.session_state.get("map_nonce", 0) + 1

    results = st.session_state.get("results")
    meta = st.session_state.get("search_meta") or {}
    if results is None:
        st.info("Set your trip above and click **Find campgrounds**.")
        return

    soft_n = sum(1 for r in results if r.get("soft_flags"))
    solid_n = len(results) - soft_n
    st.subheader(f"{solid_n} places that fit this trip")
    stay = meta.get("stay")
    range_bit = meta.get("range_label") or ""
    if stay and range_bit:
        st.caption(f"{range_bit} · staying **{stay}**")
    elif range_bit:
        st.caption(range_bit)
    if soft_n:
        st.caption(
            f"Plus **{soft_n} more** we kept but couldn't confirm — the price or party "
            "limit we hold for those is an estimate, so they're listed last and flagged."
        )
    if not results:
        st.warning("Nothing matched. Try a longer drive, a higher budget, or more camping types.")
        return
    failed_n = sum(
        1 for r in results if (r.get("availability") or {}).get("network_error")
    )
    counts = avail_counts(results)
    open_n = counts["available"] + counts["first_come"]
    checked_n = counts["checked"]
    private_n = sum(1 for r in results if r.get("agency") == "private")
    if meta.get("live") and failed_n:
        if checked_n:
            # Partial failure: say so, but don't throw away the lookups that worked.
            st.info(
                f"We reached the booking sites for {checked_n} place(s) but not for "
                f"{failed_n}. Those are marked “Check dates on Book”."
            )
        else:
            st.info(
                "We couldn’t look up dates this time. "
                "The list is still your trip matches — open **Book** to check nights."
            )
    if meta.get("live") and not checked_n and not failed_n:
        st.info(
            "These are private or glamping stays — we can’t see their calendars here. "
            "Open **Book** (or their website) for dates."
        )
    if meta.get("live") and checked_n:
        if open_n == 0:
            extra = ""
            if private_n:
                extra = (
                    f" {private_n} private listing(s) are on the list too — "
                    "check those websites."
                )
            st.warning(
                f"None of the {checked_n} public campgrounds we looked up have your "
                f"whole stay free.{extra} You can still browse below and try other "
                "nights on **Book**."
            )
        else:
            bits = []
            if counts["available"]:
                bits.append(f"{counts['available']} look reservable")
            if counts["first_come"]:
                bits.append(f"{counts['first_come']} walk-up")
            st.success(
                f"{open_n} of {checked_n} public campgrounds have your nights: "
                + ", ".join(bits)
                + ". Confirm on **Book** before you count on it."
            )
        if checked_n and meta.get("count", 0) > checked_n + private_n:
            st.caption(
                f"We look up dates for up to {MAX_LIVE_CHECKS} public campgrounds "
                "(closest first) so a huge search doesn’t take forever. "
                "Narrow how far you’ll go to check every match."
            )
    elif not meta.get("live"):
        st.caption("Dates were not looked up. Open **Book** to see calendars.")

    shown = results[:MAX_LIVE_CHECKS]
    origin_coords = meta.get("origin")
    if isinstance(origin_coords, (list, tuple)) and len(origin_coords) == 2:
        origin_tuple = (float(origin_coords[0]), float(origin_coords[1]))
    else:
        origin_tuple = None
    clicked_id = render_map(
        shown,
        origin_tuple,
        str(meta.get("city") or "Start"),
        selected_id=st.session_state.get("selected_cg_id"),
    )
    if clicked_id:
        st.session_state["selected_cg_id"] = clicked_id
    selected_id = st.session_state.get("selected_cg_id")
    selected_rec = next((r for r in shown if r.get("id") == selected_id), None)
    ordered = shown
    if selected_rec is not None:
        ordered = [selected_rec] + [r for r in shown if r.get("id") != selected_id]

    for rec in ordered:
        render_card(rec, from_map=rec.get("id") == selected_id)
    if len(results) > len(shown):
        st.caption(
            f"Showing the closest {len(shown)} of {len(results)}. "
            "Narrow how far you’ll go to see the rest."
        )


if __name__ == "__main__":
    main()
