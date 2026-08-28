"""Behaviour tests for the filtering and ranking rules.

Run with:  .venv/bin/python -m pytest test_filters.py -q
These are pure functions over the catalog — no network, fast to run.
"""

from __future__ import annotations

import json
from pathlib import Path

from dashboard import filter_catalog, price_in_range, rank_results, soft_flags

ROOT = Path(__file__).resolve().parent
CATALOG = json.loads((ROOT / "data" / "campgrounds.json").read_text())["campgrounds"]
SF = (37.7749, -122.4194)
ALL_AGENCIES = ["federal", "ca_state_parks", "private"]
ALL_TYPES = ["tent", "drive_in", "rv_hookups", "cabin_glamping", "group", "walk_in"]


def search(**over):
    kwargs = dict(
        origin=SF,
        max_miles=200.0,
        people=4,
        price_min=0,
        price_max=250,
        confirmed_price_only=False,
        types=ALL_TYPES,
        agencies=ALL_AGENCIES,
    )
    kwargs.update(over)
    return filter_catalog(CATALOG, **kwargs)


def test_price_in_range_needs_a_real_price():
    assert price_in_range({"price_min": 20, "price_max": 40}, 0, 30)
    assert not price_in_range({"price_min": 200, "price_max": 400}, 0, 30)
    assert not price_in_range({"price_min": None, "price_max": None}, 0, 300)


def test_estimated_price_outside_budget_is_kept_and_flagged():
    """The V1 bug: an estimated price silently removed the row."""
    rec = {"price_min": 110, "price_max": 225, "price_known": False, "capacity_known": True}
    flags = soft_flags(rec, people=4, price_min=0, price_max=50)
    assert len(flags) == 1 and "estimate" in flags[0]


def test_confirmed_price_outside_budget_is_a_hard_filter():
    rec = {"price_min": 110, "price_max": 225, "price_known": True, "capacity_known": True}
    assert soft_flags(rec, people=4, price_min=0, price_max=50) == []
    rows = search(price_min=0, price_max=50)
    assert all(
        not r.get("price_known") or price_in_range(r, 0, 50) for r in rows
    ), "a confirmed price outside the budget should never survive"


def test_tight_budget_no_longer_wipes_out_estimated_listings():
    """V1 dropped 228 places on guessed prices. V2 keeps them, flagged."""
    rows = search(price_min=0, price_max=50)
    kept_on_estimate = [r for r in rows if r.get("soft_flags")]
    assert kept_on_estimate, "estimated-price places should still appear"


def test_unconfirmed_capacity_does_not_exclude():
    rows = search(people=10)
    assert rows, "a party of 10 should still see options"
    guessed = [r for r in rows if not r.get("capacity_known") and r["max_people"] < 10]
    assert guessed, "places with a guessed limit below the party size should be kept"
    assert all(r.get("soft_flags") for r in guessed), "...and flagged"


def test_confirmed_capacity_below_party_is_excluded():
    rows = search(people=10)
    assert all(
        not (r.get("capacity_known") and r["max_people"] < 10) for r in rows
    ), "a confirmed limit below the party size is a real mismatch"


def test_confirmed_price_only_actually_filters():
    """The V1 checkbox could never hide anything."""
    everything = search(confirmed_price_only=False)
    confirmed = search(confirmed_price_only=True)
    assert len(confirmed) < len(everything)
    assert all(r["price_known"] for r in confirmed)


def test_hard_filters_still_bite():
    assert all(r["agency"] == "private" for r in search(agencies=["private"]))
    assert all("cabin_glamping" in r["camp_types"] for r in search(types=["cabin_glamping"]))
    assert all(r["distance_mi"] <= 50 for r in search(max_miles=50.0))


def test_flagged_rows_sort_last():
    rows = rank_results(search(price_min=0, price_max=40))
    flagged = [i for i, r in enumerate(rows) if r.get("soft_flags")]
    clean = [i for i, r in enumerate(rows) if not r.get("soft_flags")]
    if flagged and clean:
        assert min(flagged) > max(clean), "unconfirmed rows belong below confirmed ones"


def test_available_sort_still_prefers_open_sites():
    rows = search(max_miles=80.0)[:20]
    for i, r in enumerate(rows):
        r["availability"] = {"status": "available" if i % 2 else "full"}
        r["soft_flags"] = []
    ranked = rank_results(rows, sort_by="available")
    assert ranked[0]["availability"]["status"] == "available"
