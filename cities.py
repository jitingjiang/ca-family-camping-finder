"""California origin cities for the trip planner. Coords are city centers."""

from __future__ import annotations

# Latitude, longitude. Includes East Bay (Fremont, Hayward, …) and other common CA starts.
CITIES: dict[str, tuple[float, float]] = {
    "Anaheim": (33.8366, -117.9143),
    "Antioch": (38.0049, -121.8058),
    "Bakersfield": (35.3733, -119.0187),
    "Berkeley": (37.8715, -122.2730),
    "Big Sur": (36.2704, -121.8081),
    "Burbank": (34.1808, -118.3090),
    "Carlsbad": (33.1581, -117.3506),
    "Chico": (39.7285, -121.8375),
    "Concord": (37.9780, -122.0311),
    "Cupertino": (37.3230, -122.0322),
    "Daly City": (37.6879, -122.4702),
    "Davis": (38.5449, -121.7405),
    "Dublin": (37.7022, -121.9358),
    "Elk Grove": (38.4088, -121.3716),
    "Eureka": (40.8021, -124.1637),
    "Fairfield": (38.2494, -122.0400),
    "Folsom": (38.6780, -121.1760),
    "Fremont": (37.5485, -121.9886),
    "Fresno": (36.7378, -119.7871),
    "Hayward": (37.6688, -122.0808),
    "Huntington Beach": (33.6595, -117.9988),
    "Irvine": (33.6846, -117.8265),
    "Livermore": (37.6819, -121.7680),
    "Long Beach": (33.7701, -118.1937),
    "Los Angeles": (34.0522, -118.2437),
    "Mammoth Lakes": (37.6485, -118.9721),
    "Merced": (37.3022, -120.4830),
    "Milpitas": (37.4323, -121.8996),
    "Modesto": (37.6391, -120.9969),
    "Monterey": (36.6002, -121.8947),
    "Mountain View": (37.3861, -122.0839),
    "Napa": (38.2975, -122.2869),
    "Newark": (37.5297, -122.0402),
    "Oakland": (37.8044, -122.2712),
    "Oceanside": (33.1959, -117.3795),
    "Ontario": (34.0633, -117.6509),
    "Orange": (33.7879, -117.8531),
    "Oxnard": (34.1975, -119.1771),
    "Palm Springs": (33.8303, -116.5453),
    "Palo Alto": (37.4419, -122.1430),
    "Pasadena": (34.1478, -118.1445),
    "Pleasanton": (37.6624, -121.8747),
    "Redding": (40.5865, -122.3917),
    "Redwood City": (37.4852, -122.2364),
    "Richmond": (37.9358, -122.3477),
    "Riverside": (33.9533, -117.3962),
    "Roseville": (38.7521, -121.2880),
    "Sacramento": (38.5816, -121.4944),
    "Salinas": (36.6777, -121.6555),
    "San Bernardino": (34.1083, -117.2898),
    "San Diego": (32.7157, -117.1611),
    "San Francisco": (37.7749, -122.4194),
    "San Jose": (37.3382, -121.8863),
    "San Leandro": (37.7249, -122.1561),
    "San Luis Obispo": (35.2828, -120.6596),
    "San Mateo": (37.5630, -122.3255),
    "San Rafael": (37.9735, -122.5311),
    "Santa Ana": (33.7455, -117.8677),
    "Santa Barbara": (34.4208, -119.6982),
    "Santa Clara": (37.3541, -121.9552),
    "Santa Cruz": (36.9741, -122.0308),
    "Santa Rosa": (38.4404, -122.7141),
    "South Lake Tahoe": (38.9399, -119.9772),
    "Stockton": (37.9577, -121.2908),
    "Sunnyvale": (37.3688, -122.0363),
    "Temecula": (33.4936, -117.1484),
    "Thousand Oaks": (34.1706, -118.8376),
    "Torrance": (33.8358, -118.3406),
    "Truckee": (39.3280, -120.1833),
    "Union City": (37.5934, -122.0438),
    "Vallejo": (38.1041, -122.2566),
    "Ventura": (34.2746, -119.2290),
    "Visalia": (36.3302, -119.2921),
    "Walnut Creek": (37.9101, -122.0652),
    "Yosemite Valley": (37.7459, -119.5936),
}

CITY_INDEX = {name.casefold(): (name, coords) for name, coords in CITIES.items()}

NOMINATIM = "https://nominatim.openstreetmap.org/search"


def lookup_city(query: str) -> tuple[str, tuple[float, float]] | None:
    """Match a typed city name against the built-in list."""
    text = (query or "").strip()
    if not text:
        return None
    key = text.casefold()
    if key in CITY_INDEX:
        name, coords = CITY_INDEX[key]
        return name, coords
    starts = [
        (name, coords)
        for name, coords in CITIES.items()
        if name.casefold().startswith(key)
    ]
    if len(starts) == 1:
        return starts[0]
    contains = [
        (name, coords)
        for name, coords in CITIES.items()
        if key in name.casefold()
    ]
    if len(contains) == 1:
        return contains[0]
    return None


def geocode_ca_city(query: str) -> tuple[str, tuple[float, float]] | None:
    """Look up a California place via OpenStreetMap. Returns None on network failure."""
    text = (query or "").strip()
    if not text:
        return None
    import requests

    try:
        session = requests.Session()
        session.trust_env = False
        session.proxies = {"http": None, "https": None}
        response = session.get(
            NOMINATIM,
            params={
                "q": f"{text}, California, USA",
                "format": "json",
                "limit": 1,
                "countrycodes": "us",
            },
            headers={"User-Agent": "CACampingFinder/1.0 (personal trip planner)"},
            timeout=12,
        )
        response.raise_for_status()
        hits = response.json() or []
        if not hits:
            return None
        hit = hits[0]
        lat, lng = float(hit["lat"]), float(hit["lon"])
        # Keep results in/near California.
        if not (32.5 <= lat <= 42.05 and -124.5 <= lng <= -114.1):
            return None
        label = str(hit.get("display_name") or text).split(",")[0].strip() or text
        return label, (lat, lng)
    except (OSError, ValueError, KeyError, TypeError, requests.RequestException):
        return None
