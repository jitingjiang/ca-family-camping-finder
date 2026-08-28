"""Normalize campground records into one schema the dashboard can filter."""

from __future__ import annotations

import re
from typing import Any

CAMP_TYPES: dict[str, str] = {
    "tent": "Tent",
    "drive_in": "Drive-in / auto",
    "rv_hookups": "RV hookups",
    "cabin_glamping": "Cabin / yurt / glamping",
    "group": "Group",
    "walk_in": "Walk-in / hike-in",
}

AGENCY_LABELS: dict[str, str] = {
    "federal": "Federal",
    "ca_state_parks": "CA State Parks",
    "private": "Private",
}

BOOKING_LABELS: dict[str, str] = {
    "recreation_gov": "Recreation.gov",
    "reservecalifornia": "ReserveCalifornia",
    "direct": "Direct website",
}

RESERVATION_WINDOW = {
    "recreation_gov": (
        "Most Recreation.gov campgrounds open on a rolling 6-month window "
        "(new dates typically drop at 7:00 a.m. Pacific). Have an account and "
        "payment ready — popular California sites vanish in minutes."
    ),
    "reservecalifornia": (
        "CA State Parks (ReserveCalifornia) also use a rolling ~6-month window. "
        "Create a ReserveCalifornia account before the drop. Midweek and "
        "shoulder-season dates are much easier than summer weekends."
    ),
    "direct": (
        "Private and glamping stays book on the property website (or Hipcamp / "
        "Airbnb-style platforms). There is no live inventory in this app — "
        "open the site to check dates."
    ),
}

YOSEMITE_NOTE = (
    "Yosemite campgrounds are among the hardest in California. Frontcountry "
    "sites book on Recreation.gov (often a 5-month window on the 15th — confirm "
    "current NPS rules). Wilderness and some peak experiences use lotteries or "
    "timed entry on top of a campsite."
)

HTML_TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"\s+")
PEOPLE_RE = re.compile(r"up to\s+(\d+)\s+people", re.I)
NO_PETS_RE = re.compile(r"\bno pets\b|pets (are )?not|pets prohibited", re.I)
PETS_OK_RE = re.compile(r"\bpets? (are )?(welcome|allowed|ok|permitted)\b", re.I)


def strip_html(text: str | None) -> str:
    if not text:
        return ""
    cleaned = HTML_TAG_RE.sub(" ", text)
    return WHITESPACE_RE.sub(" ", cleaned).strip()


def title_name(name: str | None) -> str:
    raw = WHITESPACE_RE.sub(" ", (name or "").replace("\xa0", " ").strip())
    if not raw:
        return ""
    if raw.isupper() or raw.islower():
        return raw.title()
    return raw


def unique_types(types: list[str]) -> list[str]:
    seen: list[str] = []
    for item in types:
        if item in CAMP_TYPES and item not in seen:
            seen.append(item)
    return seen or ["tent"]


def parse_people(text: str) -> int | None:
    match = PEOPLE_RE.search(text or "")
    if match:
        return int(match.group(1))
    return None


def parse_pets(text: str) -> bool | None:
    blob = text or ""
    if NO_PETS_RE.search(blob):
        return False
    if PETS_OK_RE.search(blob):
        return True
    return None


def types_from_equipment(names: list[str] | None, extra_text: str = "") -> list[str]:
    blob = " ".join(names or []).lower() + " " + extra_text.lower()
    found: list[str] = []
    if any(word in blob for word in ("tent",)):
        found.append("tent")
    if any(
        word in blob
        for word in (
            "rv",
            "trailer",
            "fifth wheel",
            "pickup camper",
            "caravan",
            "pop up",
            "vehicle",
        )
    ):
        found.append("drive_in")
    if any(word in blob for word in ("hookup", "hook-up", "electric", "water/elec")):
        found.append("rv_hookups")
        if "drive_in" not in found:
            found.append("drive_in")
    if any(
        word in blob
        for word in ("cabin", "yurt", "lookout", "glamping", "cottage", "airstream")
    ):
        found.append("cabin_glamping")
    if "group" in blob:
        found.append("group")
    if any(word in blob for word in ("walk", "hike", "boat-in", "boat in")):
        found.append("walk_in")
    return unique_types(found)


def types_from_cnra(type_name: str, subtype: str, detail: str) -> list[str]:
    blob = f"{type_name} {subtype} {detail}".lower()
    found: list[str] = []
    if "group" in blob:
        found.append("group")
    if "hookup" in blob or "hook-up" in blob:
        found.append("rv_hookups")
        found.append("drive_in")
    if "walk" in blob or "environmental" in blob or "hike" in blob:
        found.append("walk_in")
        found.append("tent")
    if "tent only" in blob or "tent" in blob:
        found.append("tent")
    if "family" in blob or "developed" in blob or "enroute" in blob:
        found.append("drive_in")
        found.append("tent")
    if "primitive" in blob:
        found.append("tent")
    if any(word in blob for word in ("cabin", "yurt", "cottage")):
        found.append("cabin_glamping")
    return unique_types(found)


def types_from_rc_name(facility_name: str, place_name: str = "") -> list[str]:
    blob = f"{facility_name} {place_name}".lower()
    found: list[str] = []
    if "group" in blob:
        found.append("group")
    if "hookup" in blob or "hook-up" in blob or " rv" in f" {blob}":
        found.append("rv_hookups")
        found.append("drive_in")
    if any(word in blob for word in ("walk", "environmental", "hike", "backpack")):
        found.append("walk_in")
        found.append("tent")
    if any(word in blob for word in ("cabin", "yurt", "cottage", "glamping")):
        found.append("cabin_glamping")
    if "enroute" in blob or "en route" in blob:
        found.append("drive_in")
    if "tent" in blob:
        found.append("tent")
    if not found:
        found = ["tent", "drive_in"]
    return unique_types(found)


def amenities_from_text(text: str, equipment: list[str] | None = None) -> list[str]:
    blob = f"{text} {' '.join(equipment or [])}".lower()
    found: list[str] = []
    checks = [
        ("showers", ("shower",)),
        ("flush_toilets", ("flush toilet", "flush restroom")),
        ("restrooms", ("toilet", "restroom", "vault")),
        ("water", ("drinking water", "potable", "water spigot", "water hook")),
        ("hookups", ("hookup", "hook-up", "electric")),
        ("dump_station", ("dump station",)),
        ("store", ("camp store", "general store", "campstore")),
        ("accessible", ("accessible", "ada", "wheelchair")),
    ]
    for key, needles in checks:
        if any(n in blob for n in needles) and key not in found:
            found.append(key)
    return found


def state_park_price(camp_types: list[str]) -> tuple[int, int]:
    if "group" in camp_types:
        return 110, 225
    if "cabin_glamping" in camp_types:
        return 80, 160
    if "rv_hookups" in camp_types:
        return 45, 65
    if "walk_in" in camp_types:
        return 20, 35
    return 35, 45


def extra_notes(name: str, parent: str, booking_system: str) -> str:
    blob = f"{name} {parent}".lower()
    parts = [RESERVATION_WINDOW.get(booking_system, "")]
    if "yosemite" in blob:
        parts.append(YOSEMITE_NOTE)
    if any(word in blob for word in ("channel islands", "alcatraz")):
        parts.append(
            "This area often needs a boat, ferry, or extra permit on top of a campsite."
        )
    return " ".join(p for p in parts if p).strip()


def empty_record() -> dict[str, Any]:
    return {
        "id": "",
        "name": "",
        "parent_name": "",
        "city": "",
        "agency": "",
        "agency_name": "",
        "booking_system": "",
        "external_id": "",
        "place_id": "",
        "lat": None,
        "lng": None,
        "camp_types": [],
        "max_people": None,
        "pets": None,
        "amenities": [],
        "price_min": None,
        "price_max": None,
        "price_known": False,
        "booking_url": "",
        "website": "",
        "reservable": True,
        "first_come": False,
        "lottery": False,
        "notes": "",
        "description": "",
        "source": "",
        "rating": None,
        "review_count": None,
    }


def from_recgov(item: dict[str, Any]) -> dict[str, Any] | None:
    try:
        lat = float(item.get("latitude") or 0)
        lng = float(item.get("longitude") or 0)
    except (TypeError, ValueError):
        return None
    if not lat or not lng:
        return None
    entity_id = str(item.get("entity_id") or "").strip()
    if not entity_id:
        return None
    name = title_name(str(item.get("name") or ""))
    parent = str(item.get("parent_name") or "").strip()
    desc = strip_html(str(item.get("description") or ""))
    equipment = [str(x) for x in (item.get("campsite_equipment_name") or [])]
    reserve_types = [str(x) for x in (item.get("campsite_reserve_type") or [])]
    price = item.get("price_range") or {}
    price_min = price.get("amount_min")
    price_max = price.get("amount_max")
    try:
        price_min = int(price_min) if price_min is not None else None
        price_max = int(price_max) if price_max is not None else None
    except (TypeError, ValueError):
        price_min = price_max = None
    types = types_from_equipment(equipment, f"{name} {desc}")
    first_come = any("first" in t.lower() or "walk" in t.lower() for t in reserve_types)
    rec = empty_record()
    rec.update(
        {
            "id": f"federal-{entity_id}",
            "name": name,
            "parent_name": parent,
            "city": str(item.get("city") or "").strip(),
            "agency": "federal",
            "agency_name": str(item.get("org_name") or "Federal").strip(),
            "booking_system": "recreation_gov",
            "external_id": entity_id,
            "lat": lat,
            "lng": lng,
            "camp_types": types,
            "max_people": parse_people(desc) or 6,
            "pets": parse_pets(desc),
            "amenities": amenities_from_text(desc, equipment),
            "price_min": price_min if price_min is not None else 20,
            "price_max": price_max if price_max is not None else 45,
            "price_known": price_min is not None,
            "booking_url": f"https://www.recreation.gov/camping/campgrounds/{entity_id}",
            "website": str(item.get("official_site_url") or "")
            or f"https://www.recreation.gov/camping/campgrounds/{entity_id}",
            "reservable": bool(item.get("reservable", True)),
            "first_come": first_come or not item.get("reservable", True),
            "lottery": "lottery" in f"{name} {parent} {desc}".lower(),
            "notes": extra_notes(name, parent, "recreation_gov"),
            "description": desc[:800],
            "source": "recreation_gov",
            "rating": item.get("average_rating"),
            "review_count": item.get("number_of_ratings"),
        }
    )
    return rec


def from_ridb(item: dict[str, Any]) -> dict[str, Any] | None:
    ftype = str(item.get("FacilityTypeDescription") or "")
    if ftype and ftype.lower() not in {"campground", "facility"}:
        keywords = str(item.get("Keywords") or "").lower()
        name_l = str(item.get("FacilityName") or "").lower()
        if "camp" not in keywords and "camp" not in name_l:
            return None
    try:
        lat = float(item.get("FacilityLatitude") or 0)
        lng = float(item.get("FacilityLongitude") or 0)
    except (TypeError, ValueError):
        return None
    if not lat or not lng:
        return None
    fid = str(item.get("FacilityID") or "").strip()
    if not fid:
        return None
    name = title_name(str(item.get("FacilityName") or ""))
    desc = strip_html(str(item.get("FacilityDescription") or ""))
    rec_areas = item.get("RECAREA") or []
    parent = ""
    if rec_areas and isinstance(rec_areas, list):
        parent = str(rec_areas[0].get("RecAreaName") or "")
    orgs = item.get("ORGANIZATION") or []
    org_name = "Federal"
    if orgs and isinstance(orgs, list):
        org_name = str(orgs[0].get("OrgName") or org_name)
    types = types_from_equipment([], f"{name} {desc} {ftype}")
    rec = empty_record()
    rec.update(
        {
            "id": f"federal-{fid}",
            "name": name,
            "parent_name": parent,
            "agency": "federal",
            "agency_name": org_name,
            "booking_system": "recreation_gov",
            "external_id": fid,
            "lat": lat,
            "lng": lng,
            "camp_types": types,
            "max_people": parse_people(desc) or 6,
            "pets": parse_pets(desc),
            "amenities": amenities_from_text(desc),
            "price_min": 20,
            "price_max": 45,
            "price_known": False,
            "booking_url": f"https://www.recreation.gov/camping/campgrounds/{fid}",
            "website": f"https://www.recreation.gov/camping/campgrounds/{fid}",
            "reservable": bool(item.get("Reservable", True)),
            "first_come": not bool(item.get("Reservable", True)),
            "notes": extra_notes(name, parent, "recreation_gov"),
            "description": desc[:800],
            "source": "ridb",
        }
    )
    return rec


def from_reservecalifornia(
    facility: dict[str, Any], place: dict[str, Any]
) -> dict[str, Any] | None:
    facility_id = facility.get("FacilityId")
    place_id = place.get("PlaceId") or facility.get("PlaceId")
    if not facility_id or not place_id:
        return None
    try:
        lat = float(place.get("Latitude") or 0)
        lng = float(place.get("Longitude") or 0)
    except (TypeError, ValueError):
        return None
    if not lat or not lng:
        return None
    name = title_name(str(facility.get("Name") or ""))
    parent = title_name(str(place.get("Name") or place.get("Description") or ""))
    types = types_from_rc_name(name, parent)
    price_min, price_max = state_park_price(types)
    max_people = facility.get("MaxPersonOccupancy") or 0
    rec = empty_record()
    rec.update(
        {
            "id": f"state-{place_id}-{facility_id}",
            "name": name,
            "parent_name": parent,
            "city": title_name(str(place.get("City") or "")),
            "agency": "ca_state_parks",
            "agency_name": "California State Parks",
            "booking_system": "reservecalifornia",
            "external_id": str(facility_id),
            "place_id": str(place_id),
            "lat": lat,
            "lng": lng,
            "camp_types": types,
            "max_people": int(max_people) if max_people else (40 if "group" in types else 8),
            "pets": True,
            "amenities": amenities_from_text(f"{name} {parent}"),
            "price_min": price_min,
            "price_max": price_max,
            "price_known": False,
            "booking_url": "https://www.reservecalifornia.com/",
            "website": "https://www.reservecalifornia.com/",
            "reservable": bool(facility.get("AllowWebBooking", True)),
            "first_come": not bool(facility.get("AllowWebBooking", True)),
            "notes": extra_notes(name, parent, "reservecalifornia"),
            "description": strip_html(str(place.get("Description") or ""))[:800],
            "source": "reservecalifornia",
        }
    )
    return rec


def from_cnra(props: dict[str, Any], lat: float, lng: float) -> dict[str, Any] | None:
    name = title_name(str(props.get("Campground") or props.get("DETAIL") or ""))
    if not name:
        return None
    parent = title_name(str(props.get("UNITNAME") or ""))
    gis_id = str(props.get("GISID") or props.get("GlobalID") or name)
    types = types_from_cnra(
        str(props.get("TYPE") or ""),
        str(props.get("SUBTYPE") or ""),
        str(props.get("DETAIL") or ""),
    )
    price_min, price_max = state_park_price(types)
    rec = empty_record()
    rec.update(
        {
            "id": f"cnra-{gis_id}",
            "name": name,
            "parent_name": parent,
            "agency": "ca_state_parks",
            "agency_name": "California State Parks",
            "booking_system": "reservecalifornia",
            "external_id": "",
            "lat": lat,
            "lng": lng,
            "camp_types": types,
            "max_people": 40 if "group" in types else 8,
            "pets": True,
            "amenities": amenities_from_text(str(props.get("DETAIL") or "")),
            "price_min": price_min,
            "price_max": price_max,
            "price_known": False,
            "booking_url": "https://www.reservecalifornia.com/",
            "website": "https://www.parks.ca.gov/",
            "reservable": "walk" not in " ".join(types),
            "first_come": "walk_in" in types,
            "notes": extra_notes(name, parent, "reservecalifornia"),
            "description": str(props.get("DETAIL") or ""),
            "source": "cnra",
        }
    )
    return rec


def from_private(item: dict[str, Any]) -> dict[str, Any] | None:
    try:
        lat = float(item.get("lat") or 0)
        lng = float(item.get("lng") or 0)
    except (TypeError, ValueError):
        return None
    if not lat or not lng:
        return None
    rec = empty_record()
    rec.update(
        {
            "id": str(item.get("id") or f"private-{item.get('name')}"),
            "name": str(item.get("name") or "").strip(),
            "parent_name": str(item.get("parent_name") or "").strip(),
            "city": str(item.get("city") or "").strip(),
            "agency": "private",
            "agency_name": str(item.get("agency_name") or "Private").strip(),
            "booking_system": "direct",
            "external_id": "",
            "lat": lat,
            "lng": lng,
            "camp_types": unique_types(list(item.get("camp_types") or ["cabin_glamping"])),
            "max_people": item.get("max_people") or 6,
            "pets": item.get("pets"),
            "amenities": list(item.get("amenities") or []),
            "price_min": int(item.get("price_min") or 100),
            "price_max": int(item.get("price_max") or 400),
            "price_known": True,
            "booking_url": str(item.get("booking_url") or item.get("website") or ""),
            "website": str(item.get("website") or item.get("booking_url") or ""),
            "reservable": True,
            "first_come": False,
            "notes": extra_notes(
                str(item.get("name") or ""),
                str(item.get("parent_name") or ""),
                "direct",
            )
            + (" " + str(item.get("notes") or "")).rstrip(),
            "description": str(item.get("notes") or ""),
            "source": "private",
        }
    )
    return rec


def merge_federal(recgov: dict[str, Any], ridb: dict[str, Any]) -> dict[str, Any]:
    """Prefer Recreation.gov search (prices, ratings); fill gaps from RIDB."""
    merged = dict(ridb)
    for key, value in recgov.items():
        if value in (None, "", []):
            continue
        merged[key] = value
    merged["camp_types"] = unique_types(
        list(recgov.get("camp_types") or []) + list(ridb.get("camp_types") or [])
    )
    if recgov.get("price_known"):
        merged["price_min"] = recgov.get("price_min")
        merged["price_max"] = recgov.get("price_max")
        merged["price_known"] = True
    merged["source"] = "recreation_gov+ridb"
    return merged
