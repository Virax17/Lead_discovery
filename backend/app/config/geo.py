import json
import math
from pathlib import Path

_DATA_PATH = Path(__file__).resolve().parent / "geo_data.json"
with open(_DATA_PATH, encoding="utf-8") as f:
    _GEO_DATA = json.load(f)

_STATES_BY_COUNTRY: dict[str, list[dict]] = _GEO_DATA["states"]
_CITIES_BY_KEY: dict[str, list[dict]] = _GEO_DATA["cities"]


def list_states(country_code: str) -> list[dict]:
    return _STATES_BY_COUNTRY.get(country_code.strip().upper(), [])


def list_cities(country_code: str, state_code: str) -> list[dict]:
    key = f"{country_code.strip().upper()}|{state_code.strip().upper()}"
    return _CITIES_BY_KEY.get(key, [])


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in km. A degree of longitude shrinks toward the
    poles, so naive lat/lng Euclidean distance is meaningfully wrong for
    high-latitude countries (Russia, Canada) — this stays correct everywhere."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))
