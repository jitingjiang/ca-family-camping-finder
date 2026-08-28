"""On-demand, rate-limited availability for a shortlist. Never books."""

from __future__ import annotations

import time
from datetime import date, datetime, timedelta
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
RECGOV_MONTH = (
    "https://www.recreation.gov/api/camps/availability/campground/{facility_id}/month"
)
RC_CONFIG_URL = "https://www.reservecalifornia.com/config.json"
RC_API_FALLBACK = (
    "https://california-rdr.prod.cali.rd12.recreation-management.tylerapp.com/rdr/"
)

AVAILABLE_STATUSES = {"Available"}
WALKUP_STATUSES = {"Open", "Walkup", "Walk Up"}
NYR_STATUSES = {"NYR", "Not Yet Released"}
UNAVAILABLE_STATUSES = {
    "Reserved",
    "Not Available",
    "Not Reservable",
    "Not Reservable Management",
    "Not Available Cutoff",
    "Closed",
    "Lottery",
}

# After filters, check public campgrounds in that list (closest first).
# ~1.2s each; 80 ≈ 1.5 min — a polite ceiling so a statewide search cannot run for hours.
MAX_LIVE_CHECKS = 80
MIN_INTERVAL_SEC = 1.15
CACHE_TTL_SEC = 180
# Give up on live lookups only after this many failures in a row (an outage or a
# block), not after a single flaky request.
MAX_CONSECUTIVE_ERRORS = 3

_cache: dict[tuple[str, str, str, str], tuple[float, dict[str, Any]]] = {}
_last_call_at = 0.0
_rc_base: str | None = None


def make_session() -> requests.Session:
    session = requests.Session()
    # Cursor/sandbox HTTP(S)_PROXY can 403; talk to booking sites directly.
    session.trust_env = False
    session.proxies = {"http": None, "https": None}
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        }
    )
    retry = Retry(
        total=2,
        connect=0,
        read=2,
        status=2,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET", "POST"),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=4)
    session.mount("https://", adapter)
    return session


def _network_result(exc: BaseException) -> dict[str, Any]:
    result = unknown_result("network")
    result["network_error"] = True
    return result


def stay_nights(check_in: date, check_out: date) -> list[date]:
    nights: list[date] = []
    day = check_in
    while day < check_out:
        nights.append(day)
        day += timedelta(days=1)
    return nights


def _throttle() -> None:
    global _last_call_at
    wait = MIN_INTERVAL_SEC - (time.monotonic() - _last_call_at)
    if wait > 0:
        time.sleep(wait)
    _last_call_at = time.monotonic()


def _cache_get(key: tuple[str, str, str, str]) -> dict[str, Any] | None:
    hit = _cache.get(key)
    if not hit:
        return None
    stored_at, value = hit
    if time.monotonic() - stored_at > CACHE_TTL_SEC:
        _cache.pop(key, None)
        return None
    return value


def _cache_set(key: tuple[str, str, str, str], value: dict[str, Any]) -> None:
    _cache[key] = (time.monotonic(), value)


def unknown_result(reason: str = "unchecked") -> dict[str, Any]:
    return {
        "status": "unknown",
        "reason": reason,
        "label": "Check dates on Book",
        "sites_available": None,
        "detail": "",
        "checked": False,
    }


def rc_base_url(session: requests.Session) -> str:
    global _rc_base
    if _rc_base:
        return _rc_base
    try:
        response = session.get(RC_CONFIG_URL, timeout=15)
        response.raise_for_status()
        url = str((response.json() or {}).get("rdrApiUrl") or "").strip()
        if url:
            _rc_base = url if url.endswith("/") else url + "/"
            return _rc_base
    except requests.RequestException:
        pass
    _rc_base = RC_API_FALLBACK
    return _rc_base


def _month_starts(check_in: date, check_out: date) -> list[date]:
    months: list[date] = []
    cursor = date(check_in.year, check_in.month, 1)
    last = date(check_out.year, check_out.month, 1)
    while cursor <= last:
        months.append(cursor)
        if cursor.month == 12:
            cursor = date(cursor.year + 1, 1, 1)
        else:
            cursor = date(cursor.year, cursor.month + 1, 1)
    return months


def _parse_avail_day(key: str) -> date | None:
    try:
        return datetime.fromisoformat(key.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(key[:10])
        except ValueError:
            return None


def check_recreation_gov(
    session: requests.Session,
    facility_id: str,
    check_in: date,
    check_out: date,
) -> dict[str, Any]:
    nights = stay_nights(check_in, check_out)
    if not nights:
        return unknown_result("dates")
    combined: dict[str, dict[str, str]] = {}
    nyr_only = True
    saw_any = False
    try:
        for month in _month_starts(check_in, check_out):
            _throttle()
            start = f"{month:%Y-%m-01}T00:00:00.000Z"
            response = session.get(
                RECGOV_MONTH.format(facility_id=facility_id),
                params={"start_date": start},
                headers={"Referer": "https://www.recreation.gov/"},
                timeout=30,
            )
            if response.status_code >= 400:
                return unknown_result("unchecked")
            payload = response.json() or {}
            campsites = payload.get("campsites") or {}
            if not campsites:
                continue
            saw_any = True
            for site_id, site in campsites.items():
                days = combined.setdefault(str(site_id), {})
                for raw_day, status in (site.get("availabilities") or {}).items():
                    day = _parse_avail_day(str(raw_day))
                    if day:
                        days[day.isoformat()] = str(status)
    except requests.RequestException as exc:
        return _network_result(exc)
    if not saw_any:
        return unknown_result("unchecked")

    fully_open = 0
    walkup = 0
    nyr = 0
    for days in combined.values():
        statuses = [days.get(n.isoformat(), "") for n in nights]
        if not any(statuses):
            continue
        if all(s in AVAILABLE_STATUSES for s in statuses):
            fully_open += 1
            nyr_only = False
        elif all(s in WALKUP_STATUSES or s in AVAILABLE_STATUSES for s in statuses):
            walkup += 1
            nyr_only = False
        elif all(s in NYR_STATUSES for s in statuses):
            nyr += 1
        else:
            nyr_only = False

    if fully_open > 0:
        return {
            "status": "available",
            "label": "Available",
            "sites_available": fully_open,
            "detail": f"{fully_open} site(s) open for every night of this stay.",
            "checked": True,
        }
    if walkup > 0:
        return {
            "status": "first_come",
            "label": "Walk-up / first-come",
            "sites_available": walkup,
            "detail": f"{walkup} site(s) listed as walk-up for these dates.",
            "checked": True,
        }
    if nyr_only and nyr > 0:
        return {
            "status": "not_yet_released",
            "label": "Not yet released",
            "sites_available": 0,
            "detail": "These dates are not in the reservation window yet.",
            "checked": True,
        }
    return {
        "status": "full",
        "label": "No consecutive nights",
        "sites_available": 0,
        "detail": "No site is free for the whole stay. Try fewer nights or nearby dates.",
        "checked": True,
    }


def check_reservecalifornia(
    session: requests.Session,
    facility_id: str,
    check_in: date,
    check_out: date,
) -> dict[str, Any]:
    nights = stay_nights(check_in, check_out)
    if not nights:
        return unknown_result("dates")
    _throttle()
    end = check_out + timedelta(days=1)
    payload = {
        "FacilityId": int(facility_id),
        "StartDate": check_in.strftime("%m-%d-%Y"),
        "EndDate": end.strftime("%m-%d-%Y"),
        "WebOnly": True,
        "InSeasonOnly": True,
        "UnitSort": "orderby",
    }
    try:
        response = session.post(
            rc_base_url(session) + "search/grid",
            json=payload,
            timeout=35,
        )
    except requests.RequestException as exc:
        return _network_result(exc)
    if response.status_code >= 400:
        return unknown_result("unchecked")
    body = response.json() or {}
    facility = body.get("Facility") or {}
    units = facility.get("Units") or {}
    if not units:
        return unknown_result("unchecked")

    fully_open = 0
    walkup = 0
    for unit in units.values() if isinstance(units, dict) else units:
        slices = unit.get("Slices") or {}
        by_day: dict[str, dict[str, Any]] = {}
        for slice_row in slices.values() if isinstance(slices, dict) else []:
            day = str(slice_row.get("Date") or "")[:10]
            if day:
                by_day[day] = slice_row
        if not all(n.isoformat() in by_day for n in nights):
            continue
        night_rows = [by_day[n.isoformat()] for n in nights]
        if all(row.get("IsFree") for row in night_rows):
            fully_open += 1
        elif all(row.get("IsWalkin") or row.get("IsFree") for row in night_rows):
            walkup += 1

    if facility.get("IsReservationDraw"):
        return {
            "status": "lottery",
            "label": "Lottery / draw",
            "sites_available": fully_open,
            "detail": "This facility uses a reservation draw. Check ReserveCalifornia for rules.",
            "checked": True,
        }
    if fully_open > 0:
        return {
            "status": "available",
            "label": "Available",
            "sites_available": fully_open,
            "detail": f"{fully_open} site(s) open for every night of this stay.",
            "checked": True,
        }
    if walkup > 0:
        return {
            "status": "first_come",
            "label": "Walk-up / first-come",
            "sites_available": walkup,
            "detail": f"{walkup} walk-up site(s) for these dates.",
            "checked": True,
        }
    return {
        "status": "full",
        "label": "No consecutive nights",
        "sites_available": 0,
        "detail": "No site is free for the whole stay on ReserveCalifornia.",
        "checked": True,
    }


def check_one(
    campground: dict[str, Any],
    check_in: date,
    check_out: date,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    system = campground.get("booking_system")
    external_id = str(campground.get("external_id") or "")
    if system == "direct" or campground.get("agency") == "private":
        return {
            "status": "check_site",
            "reason": "private",
            "label": "Check the listing",
            "sites_available": None,
            "detail": "Dates for private stays are on the property website.",
            "checked": False,
        }
    if campground.get("first_come") and not campground.get("reservable"):
        return {
            "status": "first_come",
            "reason": "walkup",
            "label": "Walk-up",
            "sites_available": None,
            "detail": "First-come, first-served — no online hold. Arrive early.",
            "checked": False,
        }
    if not external_id:
        return unknown_result("unchecked")

    key = (system or "", external_id, check_in.isoformat(), check_out.isoformat())
    cached = _cache_get(key)
    if cached:
        return cached

    session = session or make_session()
    try:
        if system == "recreation_gov":
            result = check_recreation_gov(session, external_id, check_in, check_out)
        elif system == "reservecalifornia":
            result = check_reservecalifornia(session, external_id, check_in, check_out)
        else:
            result = unknown_result("unchecked")
    except requests.RequestException as exc:
        result = _network_result(exc)
    _cache_set(key, result)
    return result


def _eta_text(remaining: int) -> str:
    secs = max(0, int(remaining * MIN_INTERVAL_SEC))
    if secs <= 8:
        return "almost done"
    if secs < 60:
        return f"about {secs} sec left"
    minutes = (secs + 59) // 60
    return f"about {minutes} min left"


def check_shortlist(
    campgrounds: list[dict[str, Any]],
    check_in: date,
    check_out: date,
    limit: int = MAX_LIVE_CHECKS,
    progress: Any | None = None,
) -> list[dict[str, Any]]:
    """Attach availability to public campgrounds in the filtered list (closest first)."""
    session = make_session()
    live_budget = limit
    checked = 0
    total_live = min(
        limit,
        sum(
            1
            for cg in campgrounds
            if cg.get("booking_system") in {"recreation_gov", "reservecalifornia"}
            and cg.get("external_id")
        ),
    )
    out: list[dict[str, Any]] = []
    skip_live = False
    consecutive_errors = 0
    for cg in campgrounds:
        row = dict(cg)
        system = cg.get("booking_system")
        can_live = (
            live_budget > 0
            and system in {"recreation_gov", "reservecalifornia"}
            and cg.get("external_id")
        )
        if can_live and skip_live:
            skipped = unknown_result("skipped")
            skipped["network_error"] = True
            row["availability"] = skipped
            live_budget -= 1
        elif can_live:
            if progress is not None:
                progress.progress(
                    min(1.0, (checked + 1) / max(total_live, 1)),
                    text=(
                        f"Looking up dates at {cg.get('name')}… "
                        f"{checked + 1} of {total_live} ({_eta_text(total_live - checked - 1)})"
                    ),
                )
            avail = check_one(cg, check_in, check_out, session=session)
            row["availability"] = avail
            live_budget -= 1
            checked += 1
            # One flaky campground shouldn't abandon the rest of the list. Only give up
            # once several in a row fail, which is what a real outage or block looks like.
            if avail.get("network_error"):
                consecutive_errors += 1
                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    skip_live = True
            else:
                consecutive_errors = 0
        elif system == "direct":
            row["availability"] = check_one(cg, check_in, check_out, session=session)
        else:
            row["availability"] = unknown_result("not_in_shortlist")
        out.append(row)
    if progress is not None:
        progress.empty()
    return out
