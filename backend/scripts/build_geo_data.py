"""One-off build script: converts the open countries-states-cities dataset
(https://github.com/dr5hn/countries-states-cities-database, ODbL-1.0) into a
compact JSON file bundled with the backend for the location dropdowns and map
centering (features F2/F3). Not run at app startup - re-run manually if the
dataset needs refreshing.

Usage:
    venv/Scripts/python.exe scripts/build_geo_data.py path/to/countries+states+cities.json
"""
import json
import sys
from pathlib import Path

from app.config.countries import COUNTRY_CODE_BY_NAME

OUTPUT_PATH = Path(__file__).resolve().parent.parent / "app" / "config" / "geo_data.json"


def build(source_path: str) -> None:
    with open(source_path, encoding="utf-8") as f:
        countries = json.load(f)

    known_codes = set(COUNTRY_CODE_BY_NAME.values())

    states_by_country: dict[str, list[dict]] = {}
    cities_by_key: dict[str, list[dict]] = {}

    for country in countries:
        country_code = (country.get("iso2") or "").upper()
        if not country_code or country_code not in known_codes:
            continue

        state_list = []
        seen_state_codes: set[str] = set()

        for state in country.get("states", []):
            state_code = (state.get("iso2") or "").upper()
            if not state_code or state_code in seen_state_codes:
                continue
            seen_state_codes.add(state_code)

            lat = state.get("latitude")
            lng = state.get("longitude")
            state_list.append({
                "name": state["name"],
                "code": state_code,
                "lat": float(lat) if lat not in (None, "") else None,
                "lng": float(lng) if lng not in (None, "") else None,
            })

            city_list = []
            for city in state.get("cities", []):
                clat = city.get("latitude")
                clng = city.get("longitude")
                if clat in (None, "") or clng in (None, ""):
                    continue
                city_list.append({
                    "name": city["name"],
                    "lat": float(clat),
                    "lng": float(clng),
                })

            if city_list:
                city_list.sort(key=lambda c: c["name"])
                cities_by_key[f"{country_code}|{state_code}"] = city_list

        if state_list:
            state_list.sort(key=lambda s: s["name"])
            states_by_country[country_code] = state_list

    payload = {
        "states": states_by_country,
        "cities": cities_by_key,
    }

    OUTPUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    total_states = sum(len(v) for v in states_by_country.values())
    total_cities = sum(len(v) for v in cities_by_key.values())
    size_mb = OUTPUT_PATH.stat().st_size / (1024 * 1024)
    print(f"Wrote {OUTPUT_PATH} ({size_mb:.1f} MB): {len(states_by_country)} countries, "
          f"{total_states} states, {total_cities} cities.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    build(sys.argv[1])
