import json
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
