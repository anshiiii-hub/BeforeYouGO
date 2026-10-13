"""Static geographic reference data (city centroids), NOT event data.

Coordinates are approximate city-centre points used only to estimate straight-line
distances between cities. Event records never receive coordinates from this table;
distances are computed on demand and always labelled as approximate.
"""

from __future__ import annotations

import math
import re
import unicodedata

# canonical city -> (lat, lon, state/region, country)
CITIES: dict[str, tuple[float, float, str, str]] = {
    "Delhi": (28.6139, 77.2090, "Delhi", "India"),
    "Gurugram": (28.4595, 77.0266, "Haryana", "India"),
    "Noida": (28.5355, 77.3910, "Uttar Pradesh", "India"),
    "Greater Noida": (28.4744, 77.5040, "Uttar Pradesh", "India"),
    "Faridabad": (28.4089, 77.3178, "Haryana", "India"),
    "Ghaziabad": (28.6692, 77.4538, "Uttar Pradesh", "India"),
    "Chandigarh": (30.7333, 76.7794, "Chandigarh", "India"),
    "Mohali": (30.7046, 76.7179, "Punjab", "India"),
    "Panchkula": (30.6942, 76.8606, "Haryana", "India"),
    "Ludhiana": (30.9010, 75.8573, "Punjab", "India"),
    "Amritsar": (31.6340, 74.8723, "Punjab", "India"),
    "Jalandhar": (31.3260, 75.5762, "Punjab", "India"),
    "Patiala": (30.3398, 76.3869, "Punjab", "India"),
    "Ambala": (30.3782, 76.7767, "Haryana", "India"),
    "Rohtak": (28.8955, 76.6066, "Haryana", "India"),
    "Sonipat": (28.9931, 77.0151, "Haryana", "India"),
    "Kurukshetra": (29.9695, 76.8783, "Haryana", "India"),
    "Hisar": (29.1492, 75.7217, "Haryana", "India"),
    "Roorkee": (29.8543, 77.8880, "Uttarakhand", "India"),
    "Dehradun": (30.3165, 78.0322, "Uttarakhand", "India"),
    "Shimla": (31.1048, 77.1734, "Himachal Pradesh", "India"),
    "Jammu": (32.7266, 74.8570, "Jammu and Kashmir", "India"),
    "Srinagar": (34.0837, 74.7973, "Jammu and Kashmir", "India"),
    "Jaipur": (26.9124, 75.7873, "Rajasthan", "India"),
    "Jodhpur": (26.2389, 73.0243, "Rajasthan", "India"),
    "Udaipur": (24.5854, 73.7125, "Rajasthan", "India"),
    "Lucknow": (26.8467, 80.9462, "Uttar Pradesh", "India"),
    "Kanpur": (26.4499, 80.3319, "Uttar Pradesh", "India"),
    "Varanasi": (25.3176, 82.9739, "Uttar Pradesh", "India"),
    "Patna": (25.5941, 85.1376, "Bihar", "India"),
    "Ranchi": (23.3441, 85.3096, "Jharkhand", "India"),
    "Mumbai": (19.0760, 72.8777, "Maharashtra", "India"),
    "Pune": (18.5204, 73.8567, "Maharashtra", "India"),
    "Nagpur": (21.1458, 79.0882, "Maharashtra", "India"),
    "Nashik": (19.9975, 73.7898, "Maharashtra", "India"),
    "Ahmedabad": (23.0225, 72.5714, "Gujarat", "India"),
    "Gandhinagar": (23.2156, 72.6369, "Gujarat", "India"),
    "Surat": (21.1702, 72.8311, "Gujarat", "India"),
    "Vadodara": (22.3072, 73.1812, "Gujarat", "India"),
    "Indore": (22.7196, 75.8577, "Madhya Pradesh", "India"),
    "Bhopal": (23.2599, 77.4126, "Madhya Pradesh", "India"),
    "Raipur": (21.2514, 81.6296, "Chhattisgarh", "India"),
    "Bengaluru": (12.9716, 77.5946, "Karnataka", "India"),
    "Mysuru": (12.2958, 76.6394, "Karnataka", "India"),
    "Mangaluru": (12.9141, 74.8560, "Karnataka", "India"),
    "Chennai": (13.0827, 80.2707, "Tamil Nadu", "India"),
    "Coimbatore": (11.0168, 76.9558, "Tamil Nadu", "India"),
    "Madurai": (9.9252, 78.1198, "Tamil Nadu", "India"),
    "Hyderabad": (17.3850, 78.4867, "Telangana", "India"),
    "Visakhapatnam": (17.6868, 83.2185, "Andhra Pradesh", "India"),
    "Vijayawada": (16.5062, 80.6480, "Andhra Pradesh", "India"),
    "Kochi": (9.9312, 76.2673, "Kerala", "India"),
    "Thiruvananthapuram": (8.5241, 76.9366, "Kerala", "India"),
    "Kozhikode": (11.2588, 75.7804, "Kerala", "India"),
    "Kolkata": (22.5726, 88.3639, "West Bengal", "India"),
    "Bhubaneswar": (20.2961, 85.8245, "Odisha", "India"),
    "Guwahati": (26.1445, 91.7362, "Assam", "India"),
    "Panaji": (15.4909, 73.8278, "Goa", "India"),
    # a few international hubs so non-Indian events can still be placed approximately
    "Singapore": (1.3521, 103.8198, "", "Singapore"),
    "London": (51.5074, -0.1278, "", "United Kingdom"),
    "Berlin": (52.5200, 13.4050, "", "Germany"),
    "Paris": (48.8566, 2.3522, "", "France"),
    "Amsterdam": (52.3676, 4.9041, "", "Netherlands"),
    "New York": (40.7128, -74.0060, "New York", "United States"),
    "San Francisco": (37.7749, -122.4194, "California", "United States"),
    "Tokyo": (35.6762, 139.6503, "", "Japan"),
    "Dubai": (25.2048, 55.2708, "", "United Arab Emirates"),
}

ALIASES: dict[str, str] = {
    "new delhi": "Delhi",
    "delhi ncr": "Delhi",
    "gurgaon": "Gurugram",
    "bangalore": "Bengaluru",
    "bengaluru": "Bengaluru",
    "bombay": "Mumbai",
    "madras": "Chennai",
    "calcutta": "Kolkata",
    "trivandrum": "Thiruvananthapuram",
    "cochin": "Kochi",
    "mysore": "Mysuru",
    "mangalore": "Mangaluru",
    "vizag": "Visakhapatnam",
    "panjim": "Panaji",
    "baroda": "Vadodara",
    "banaras": "Varanasi",
    "sas nagar": "Mohali",
    "s.a.s. nagar": "Mohali",
    "nyc": "New York",
    "sf": "San Francisco",
}

REGIONS: dict[str, list[str]] = {
    "delhi ncr": ["Delhi", "Gurugram", "Noida", "Greater Noida", "Faridabad", "Ghaziabad", "Sonipat"],
    "ncr": ["Delhi", "Gurugram", "Noida", "Greater Noida", "Faridabad", "Ghaziabad", "Sonipat"],
    "tricity": ["Chandigarh", "Mohali", "Panchkula"],
    "chandigarh tricity": ["Chandigarh", "Mohali", "Panchkula"],
}

COUNTRY_ALIASES = {
    "usa": "United States",
    "us": "United States",
    "u.s.": "United States",
    "u.s.a.": "United States",
    "united states of america": "United States",
    "america": "United States",
    "uk": "United Kingdom",
    "u.k.": "United Kingdom",
    "uae": "United Arab Emirates",
    "republic of india": "India",
    "bharat": "India",
}


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text.strip().lower())


_FOLDED_CITIES = {_fold(c): c for c in CITIES}


def canonical_city(name: str | None) -> str | None:
    """Return the canonical spelling for a known city, otherwise the cleaned input."""
    if not name or not name.strip():
        return None
    folded = _fold(name)
    if folded in ALIASES:
        return ALIASES[folded]
    if folded in _FOLDED_CITIES:
        return _FOLDED_CITIES[folded]
    return re.sub(r"\s+", " ", name.strip())


def canonical_country(name: str | None) -> str | None:
    if not name or not name.strip():
        return None
    folded = _fold(name)
    return COUNTRY_ALIASES.get(folded, re.sub(r"\s+", " ", name.strip()))


def city_coords(name: str | None) -> tuple[float, float] | None:
    c = canonical_city(name)
    if c and c in CITIES:
        lat, lon, _, _ = CITIES[c]
        return lat, lon
    return None


def region_cities(name: str) -> list[str] | None:
    folded = _fold(name)
    if folded in REGIONS:
        return REGIONS[folded]
    return None


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    d = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371.0088 * math.asin(math.sqrt(d))


def approx_distance_km(city_a: str | None, city_b: str | None) -> float | None:
    """Straight-line distance between two known city centres, or None when either is unknown."""
    a, b = city_coords(city_a), city_coords(city_b)
    if a is None or b is None:
        return None
    return round(haversine_km(a, b), 1)


def known_city_names() -> list[str]:
    return sorted(CITIES)
