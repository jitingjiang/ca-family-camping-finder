"""Build a California campground catalog from official/open sources plus a private list."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from normalize import (
    from_cnra,
    from_private,
    from_recgov,
    from_reservecalifornia,
    from_ridb,
    merge_federal,
    strip_html,
    types_from_cnra,
    unique_types,
)

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
CAMPGROUNDS_JSON = DATA_DIR / "campgrounds.json"
PRIVATE_JSON = DATA_DIR / "private_glamping.json"

USER_AGENT = (
    "CACampingFinder/1.0 (personal trip planner; "
    "https://github.com/local; catalog ingest)"
)
RIDB_BASE = "https://ridb.recreation.gov/api/v1"
RECGOV_SEARCH = "https://www.recreation.gov/api/search"
CNRA_GEOJSON = (
    "https://services2.arcgis.com/AhxrK3F6WM8ECvDi/arcgis/rest/services/"
    "Campgrounds/FeatureServer/0/query"
)
RC_CONFIG_URL = "https://www.reservecalifornia.com/config.json"
RC_API_FALLBACK = (
    "https://california-rdr.prod.cali.rd12.recreation-management.tylerapp.com/rdr/"
)

# California bounding box used to drop Nevada/Arizona hits from a wide radius search.
CA_LAT = (32.5, 42.05)
CA_LNG = (-124.5, -114.1)
CA_CENTER = (37.2, -119.6)
CA_RADIUS_MI = 460

NAME_STRIP = (
    " campground",
    " campgrounds",
    " camp area",
    " campsites",
    " campsite",
    " camp",
    " sp",
    " sra",
    " sb",
    " shp",
    " svra",
    " state park",
    " state beach",
    " state recreation area",
)


def make_session() -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    session.proxies = {"http": None, "https": None}
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        }
    )
    retry = Retry(
        total=5,
        connect=3,
        read=3,
        status=5,
        backoff_factor=0.6,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET", "POST"),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=8)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def load_ridb_key() -> str | None:
    for path in (ROOT / ".env", ROOT.parent / ".env"):
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("RIDB_API_KEY="):
                value = line.split("=", 1)[1].strip().strip("'\"")
                return value or None
    return os.environ.get("RIDB_API_KEY") or None


def in_california(lat: float, lng: float) -> bool:
    return CA_LAT[0] <= lat <= CA_LAT[1] and CA_LNG[0] <= lng <= CA_LNG[1]


def norm_name(value: str) -> str:
    text = strip_html(value or "").lower()
    for suffix in NAME_STRIP:
        text = text.replace(suffix, " ")
    return " ".join(text.split())


def names_overlap(a: str, b: str) -> bool:
    na, nb = norm_name(a), norm_name(b)
    if not na or not nb:
        return False
    if na == nb or na in nb or nb in na:
        return True
    tokens_a = set(na.split())
    tokens_b = set(nb.split())
    if not tokens_a or not tokens_b:
        return False
    return len(tokens_a & tokens_b) >= min(2, len(tokens_a), len(tokens_b)) and (
        len(tokens_a & tokens_b) / len(tokens_a | tokens_b) >= 0.5
    )


def fetch_recgov_campgrounds(session: requests.Session) -> list[dict[str, Any]]:
    print("Fetching Recreation.gov campgrounds in California…")
    results: list[dict[str, Any]] = []
    start = 0
    size = 50
    total = None
    while True:
        params = {
            "fq": "entity_type:campground",
            "lat": CA_CENTER[0],
            "lng": CA_CENTER[1],
            "radius": CA_RADIUS_MI,
            "size": size,
            "start": start,
        }
        response = session.get(
            RECGOV_SEARCH,
            params=params,
            headers={"Referer": "https://www.recreation.gov/"},
            timeout=45,
        )
        response.raise_for_status()
        payload = response.json()
        page = payload.get("results") or []
        total = int(payload.get("total") or 0)
        results.extend(page)
        print(f"  rec.gov {len(results)}/{total}")
        start += size
        if not page or start >= total:
            break
        time.sleep(0.25)
    kept: list[dict[str, Any]] = []
    for item in results:
        state = str(item.get("state_code") or "")
        if state not in {"California", "CA"}:
            continue
        try:
            lat = float(item.get("latitude") or 0)
            lng = float(item.get("longitude") or 0)
        except (TypeError, ValueError):
            continue
        if in_california(lat, lng):
            kept.append(item)
    print(f"  kept {len(kept)} California campgrounds")
    return kept


def fetch_ridb_campgrounds(
    session: requests.Session, api_key: str
) -> list[dict[str, Any]]:
    print("Fetching RIDB facilities for CA (official API)…")
    headers = {"apikey": api_key, "Accept": "application/json"}
    records: list[dict[str, Any]] = []
    offset = 0
    limit = 50
    while True:
        response = session.get(
            f"{RIDB_BASE}/facilities",
            headers=headers,
            params={
                "state": "CA",
                "limit": limit,
                "offset": offset,
                "full": "true",
                "activity": "9",
            },
            timeout=45,
        )
        if response.status_code == 401:
            print("  RIDB key rejected; skipping official API.", file=sys.stderr)
            return []
        response.raise_for_status()
        payload = response.json()
        page = payload.get("RECDATA") or []
        meta = payload.get("METADATA") or {}
        results_meta = meta.get("RESULTS") or {}
        total = int(results_meta.get("TOTAL_COUNT") or 0)
        records.extend(page)
        offset += limit
        print(f"  RIDB {len(records)}/{total or '?'}")
        if not page or (total and offset >= total):
            break
        time.sleep(0.2)
    print(f"  RIDB returned {len(records)} facilities")
    return records


def rc_base_url(session: requests.Session) -> str:
    try:
        response = session.get(RC_CONFIG_URL, timeout=20)
        response.raise_for_status()
        url = str((response.json() or {}).get("rdrApiUrl") or "").strip()
        if url:
            return url if url.endswith("/") else url + "/"
    except requests.RequestException:
        pass
    return RC_API_FALLBACK


def fetch_reservecalifornia(
    session: requests.Session,
) -> tuple[list[dict[str, Any]], dict[int, dict[str, Any]]]:
    print("Fetching ReserveCalifornia places and facilities…")
    base = rc_base_url(session)
    places_resp = session.get(base + "fd/places", timeout=60)
    places_resp.raise_for_status()
    places = places_resp.json() or []
    fac_resp = session.get(base + "fd/facilities", timeout=60)
    fac_resp.raise_for_status()
    facilities = fac_resp.json() or []
    place_by_id = {int(p["PlaceId"]): p for p in places if p.get("PlaceId") is not None}
    print(f"  {len(places)} parks, {len(facilities)} facilities")
    return facilities, place_by_id


def fetch_cnra(session: requests.Session) -> list[dict[str, Any]]:
    print("Fetching CA State Parks campground GIS (CNRA)…")
    response = session.get(
        CNRA_GEOJSON,
        params={
            "where": "1=1",
            "outFields": "*",
            "f": "geojson",
            "outSR": "4326",
            "resultRecordCount": 2000,
        },
        timeout=60,
    )
    response.raise_for_status()
    features = (response.json() or {}).get("features") or []
    print(f"  {len(features)} CNRA points")
    return features


def load_private() -> list[dict[str, Any]]:
    if not PRIVATE_JSON.exists():
        return []
    payload = json.loads(PRIVATE_JSON.read_text(encoding="utf-8"))
    return list(payload.get("campgrounds") or [])


def enrich_state_with_cnra(
    records: list[dict[str, Any]], features: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    cnra_rows: list[dict[str, Any]] = []
    for feature in features:
        geom = feature.get("geometry") or {}
        coords = geom.get("coordinates") or [None, None]
        try:
            lng, lat = float(coords[0]), float(coords[1])
        except (TypeError, ValueError, IndexError):
            continue
        rec = from_cnra(feature.get("properties") or {}, lat, lng)
        if rec:
            cnra_rows.append(rec)

    matched_ids: set[str] = set()
    for rec in records:
        if rec.get("agency") != "ca_state_parks":
            continue
        for cnra in cnra_rows:
            if cnra["id"] in matched_ids:
                continue
            if names_overlap(rec["name"], cnra["name"]) or (
                names_overlap(rec.get("parent_name") or "", cnra.get("parent_name") or "")
                and names_overlap(rec["name"], cnra.get("description") or cnra["name"])
            ):
                rec["camp_types"] = unique_types(
                    list(rec.get("camp_types") or []) + list(cnra.get("camp_types") or [])
                )
                if cnra.get("description") and not rec.get("description"):
                    rec["description"] = cnra["description"]
                extra_types = types_from_cnra("", "", cnra.get("description") or "")
                if extra_types:
                    rec["camp_types"] = unique_types(
                        list(rec["camp_types"]) + extra_types
                    )
                matched_ids.add(cnra["id"])
                break

    extras: list[dict[str, Any]] = []
    for cnra in cnra_rows:
        if cnra["id"] in matched_ids:
            continue
        if "walk_in" not in (cnra.get("camp_types") or []):
            continue
        if any(names_overlap(cnra["name"], rec["name"]) for rec in records):
            continue
        extras.append(cnra)
    print(f"  CNRA matched {len(matched_ids)}; added {len(extras)} extra walk-up / unmatched sites")
    return records + extras


def build_catalog(session: requests.Session) -> list[dict[str, Any]]:
    recgov_items = fetch_recgov_campgrounds(session)
    federal_by_id: dict[str, dict[str, Any]] = {}
    for item in recgov_items:
        rec = from_recgov(item)
        if rec:
            federal_by_id[rec["external_id"]] = rec

    ridb_key = load_ridb_key()
    if ridb_key:
        for item in fetch_ridb_campgrounds(session, ridb_key):
            rec = from_ridb(item)
            if not rec:
                continue
            existing = federal_by_id.get(rec["external_id"])
            federal_by_id[rec["external_id"]] = (
                merge_federal(existing, rec) if existing else rec
            )
    else:
        print("No RIDB_API_KEY set; federal catalog is Recreation.gov search only.")

    facilities, places = fetch_reservecalifornia(session)
    state_records: list[dict[str, Any]] = []
    for facility in facilities:
        if not facility.get("AllowWebBooking", True):
            continue
        place = places.get(int(facility.get("PlaceId") or 0))
        if not place:
            continue
        rec = from_reservecalifornia(facility, place)
        if rec:
            state_records.append(rec)

    cnra_features = fetch_cnra(session)
    state_records = enrich_state_with_cnra(state_records, cnra_features)

    private_records: list[dict[str, Any]] = []
    for item in load_private():
        rec = from_private(item)
        if rec:
            private_records.append(rec)

    catalog = list(federal_by_id.values()) + state_records + private_records
    catalog.sort(key=lambda r: (r.get("agency") or "", r.get("name") or ""))
    return catalog


# A source that times out mid-run produces a short catalog rather than an error, so
# compare against what is already on disk and refuse a suspicious drop. Checked per
# agency as well as overall: losing every state park still leaves ~57% of the total,
# which a whole-catalog threshold on its own would wave through.
SHRINK_LIMIT = 0.8


def previous_counts() -> tuple[int, dict[str, int]] | None:
    """(total, by_agency) from the catalog already on disk, or None if there isn't one."""
    if not CAMPGROUNDS_JSON.exists():
        return None
    try:
        payload = json.loads(CAMPGROUNDS_JSON.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    records = payload.get("campgrounds")
    if not isinstance(records, list) or not records:
        return None
    total = int(payload.get("campground_count") or len(records))
    by_agency = payload.get("by_agency")
    if not isinstance(by_agency, dict):
        by_agency = {}
        for rec in records:
            key = rec.get("agency") or "unknown"
            by_agency[key] = by_agency.get(key, 0) + 1
    return total, {str(k): int(v) for k, v in by_agency.items()}


def shrink_warnings(new_total: int, new_agencies: dict[str, int]) -> list[str]:
    """Ways this catalog looks like a failed run rather than a real change."""
    previous = previous_counts()
    if previous is None:
        return []
    old_total, old_agencies = previous
    problems: list[str] = []
    if new_total < old_total * SHRINK_LIMIT:
        problems.append(
            f"total {old_total} -> {new_total} ({new_total / old_total:.0%} of before)"
        )
    for agency, old_count in sorted(old_agencies.items()):
        if old_count <= 0:
            continue
        new_count = new_agencies.get(agency, 0)
        if new_count < old_count * SHRINK_LIMIT:
            problems.append(
                f"{agency} {old_count} -> {new_count} "
                f"({new_count / old_count:.0%} of before)"
            )
    return problems


def write_catalog(records: list[dict[str, Any]], force: bool = False) -> bool:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    agencies: dict[str, int] = {}
    for rec in records:
        agencies[rec.get("agency") or "unknown"] = (
            agencies.get(rec.get("agency") or "unknown", 0) + 1
        )

    problems = shrink_warnings(len(records), agencies)
    if problems and not force:
        print("Refusing to overwrite the catalog — this run looks incomplete:", file=sys.stderr)
        for line in problems:
            print(f"  {line}", file=sys.stderr)
        print(
            f"\nA source probably timed out or blocked us. The existing "
            f"{CAMPGROUNDS_JSON.name} is untouched — try again in a while.\n"
            f"If the drop is real, re-run with --force to write it anyway.",
            file=sys.stderr,
        )
        return False
    if problems:
        print("--force given, writing a shrunken catalog anyway:", file=sys.stderr)
        for line in problems:
            print(f"  {line}", file=sys.stderr)

    payload = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "campground_count": len(records),
        "by_agency": agencies,
        "campgrounds": records,
    }
    CAMPGROUNDS_JSON.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"Wrote {len(records)} campgrounds → {CAMPGROUNDS_JSON}")
    for agency, count in sorted(agencies.items()):
        print(f"  {agency}: {count}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest a CA camping catalog.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Write the catalog even if it shrank enough to look like a failed run.",
    )
    args = parser.parse_args()
    session = make_session()
    records = build_catalog(session)
    if not records:
        print("No campgrounds ingested.", file=sys.stderr)
        return 1
    if not write_catalog(records, force=args.force):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
